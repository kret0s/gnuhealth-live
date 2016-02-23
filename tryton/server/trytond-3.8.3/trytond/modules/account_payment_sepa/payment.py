# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import datetime
import os
import unicodedata
from itertools import groupby
from io import BytesIO

import genshi
import genshi.template
from lxml import etree
from sql import Literal

from trytond.pool import PoolMeta, Pool
from trytond.model import (ModelSQL, ModelView, Workflow, fields, dualmethod,
    Unique)
from trytond.pyson import Eval, If
from trytond.transaction import Transaction
from trytond.tools import reduce_ids, grouped_slice
from trytond import backend
from trytond.modules.company import CompanyReport

from .sepa_handler import CAMT054

__metaclass__ = PoolMeta
__all__ = ['Journal', 'Group', 'Payment', 'Mandate', 'Message',
    'MandateReport']


class Journal:
    __name__ = 'account.payment.journal'
    company_party = fields.Function(fields.Many2One('party.party',
            'Company Party'), 'on_change_with_company_party')
    sepa_bank_account_number = fields.Many2One('bank.account.number',
        'Bank Account Number', states={
            'required': Eval('process_method') == 'sepa',
            'invisible': Eval('process_method') != 'sepa',
            },
        domain=[
            ('type', '=', 'iban'),
            ('account.owners', '=', Eval('company_party')),
            ],
        depends=['process_method', 'company_party'])
    sepa_payable_flavor = fields.Selection([
            (None, ''),
            ('pain.001.001.03', 'pain.001.001.03'),
            ('pain.001.001.05', 'pain.001.001.05'),
            ('pain.001.003.03', 'pain.001.003.03'),
            ], 'Payable Flavor', states={
            'required': Eval('process_method') == 'sepa',
            'invisible': Eval('process_method') != 'sepa',
            },
        translate=False,
        depends=['process_method'])
    sepa_receivable_flavor = fields.Selection([
            (None, ''),
            ('pain.008.001.02', 'pain.008.001.02'),
            ('pain.008.001.04', 'pain.008.001.04'),
            ('pain.008.003.02', 'pain.008.003.02'),
            ], 'Receivable Flavor', states={
            'required': Eval('process_method') == 'sepa',
            'invisible': Eval('process_method') != 'sepa',
            },
        translate=False,
        depends=['process_method'])
    sepa_batch_booking = fields.Boolean('Batch Booking', states={
            'invisible': Eval('process_method') != 'sepa',
            },
        depends=['process_method'])
    sepa_charge_bearer = fields.Selection([
            ('DEBT', 'Debtor'),
            ('CRED', 'Creditor'),
            ('SHAR', 'Shared'),
            ('SLEV', 'Service Level'),
            ], 'Charge Bearer', states={
            'required': Eval('process_method') == 'sepa',
            'invisible': Eval('process_method') != 'sepa',
            },
        depends=['process_method'])

    @classmethod
    def __setup__(cls):
        super(Journal, cls).__setup__()
        sepa_method = ('sepa', 'SEPA')
        if sepa_method not in cls.process_method.selection:
            cls.process_method.selection.append(sepa_method)

    @classmethod
    def default_company_party(cls):
        pool = Pool()
        Company = pool.get('company.company')
        company_id = cls.default_company()
        if company_id:
            return Company(company_id).party.id

    @fields.depends('company')
    def on_change_with_company_party(self, name=None):
        if self.company:
            return self.company.party.id

    @staticmethod
    def default_sepa_charge_bearer():
        return 'SLEV'


def remove_comment(stream):
    for kind, data, pos in stream:
        if kind is genshi.core.COMMENT:
            continue
        yield kind, data, pos


loader = genshi.template.TemplateLoader(
    os.path.join(os.path.dirname(__file__), 'template'),
    auto_reload=True)


class Group:
    __name__ = 'account.payment.group'
    sepa_messages = fields.One2Many('account.payment.sepa.message', 'origin',
        'SEPA Messages', readonly=True,
        domain=[('company', '=', Eval('company', -1))],
        states={
            'invisible': ~Eval('sepa_messages'),
            },
        depends=['company'])

    @classmethod
    def __setup__(cls):
        super(Group, cls).__setup__()
        cls._error_messages.update({
                'no_mandate': 'No valid mandate for payment "%s"',
                })
        cls._buttons.update({
                'generate_message': {},
                })

    def get_sepa_template(self):
        if self.kind == 'payable':
            return loader.load('%s.xml' % self.journal.sepa_payable_flavor)
        elif self.kind == 'receivable':
            return loader.load('%s.xml' % self.journal.sepa_receivable_flavor)

    def process_sepa(self):
        pool = Pool()
        Payment = pool.get('account.payment')
        if self.kind == 'receivable':
            mandates = Payment.get_sepa_mandates(self.payments)
            for payment, mandate in zip(self.payments, mandates):
                if not mandate:
                    self.raise_user_error('no_mandate', payment.rec_name)
                # Write one by one becasue mandate.sequence_type must be
                # recomputed each time
                Payment.write([payment], {
                        'sepa_mandate': mandate,
                        'sepa_mandate_sequence_type': mandate.sequence_type,
                        })
        self.generate_message(_save=False)

    @dualmethod
    @ModelView.button
    def generate_message(cls, groups, _save=True):
        pool = Pool()
        Message = pool.get('account.payment.sepa.message')
        for group in groups:
            tmpl = group.get_sepa_template()
            if not tmpl:
                raise NotImplementedError
            if not group.sepa_messages:
                group.sepa_messages = ()
            message = tmpl.generate(group=group,
                datetime=datetime, normalize=unicodedata.normalize,
                ).filter(remove_comment).render()
            message = Message(message=message, type='out', state='waiting',
                company=group.company)
            group.sepa_messages += (message,)
        if _save:
            cls.save(groups)

    @property
    def sepa_initiating_party(self):
        return self.company.party

    def sepa_group_payment_key(self, payment):
        key = (('date', payment.date),)
        if self.kind == 'receivable':
            key += (('sequence_type', payment.sepa_mandate_sequence_type),)
            key += (('scheme', payment.sepa_mandate.scheme),)
        return key

    def sepa_group_payment_id(self, key):
        payment_id = str(key['date'].toordinal())
        if self.kind == 'receivable':
            payment_id += '-' + key['sequence_type']
        return payment_id

    @property
    def sepa_payments(self):
        keyfunc = self.sepa_group_payment_key
        payments = sorted(self.payments, key=keyfunc)
        for key, grouped_payments in groupby(payments, key=keyfunc):
            yield dict(key), list(grouped_payments)


class Payment:
    __name__ = 'account.payment'

    sepa_mandate = fields.Many2One('account.payment.sepa.mandate', 'Mandate',
        ondelete='RESTRICT',
        domain=[
            ('party', '=', Eval('party', -1)),
            ('company', '=', Eval('company', -1)),
            ],
        depends=['party', 'company'])
    sepa_mandate_sequence_type = fields.Char('Mandate Sequence Type',
        readonly=True)
    sepa_return_reason_code = fields.Char('Return Reason Code', readonly=True,
        states={
            'invisible': (~Eval('sepa_return_reason_code')
                & (Eval('state') != 'failed')),
            },
        depends=['state'])
    sepa_return_reason_information = fields.Text('Return Reason Information',
        readonly=True,
        states={
            'invisible': (~Eval('sepa_return_reason_information')
                & (Eval('state') != 'failed')),
            },
        depends=['state'])
    sepa_end_to_end_id = fields.Function(fields.Char('SEPA End To End ID'),
        'get_sepa_end_to_end_id', searcher='search_end_to_end_id')
    sepa_instruction_id = fields.Function(fields.Char('SEPA Instruction ID'),
        'get_sepa_instruction_id', searcher='search_sepa_instruction_id')

    @classmethod
    def copy(cls, payments, default=None):
        if default is None:
            default = {}
        default.setdefault('sepa_mandate_sequence_type', None)
        return super(Payment, cls).copy(payments, default=default)

    @classmethod
    def get_sepa_mandates(cls, payments):
        mandates = []
        for payment in payments:
            if payment.sepa_mandate:
                if payment.sepa_mandate.is_valid:
                    mandate = payment.sepa_mandate
                else:
                    mandate = None
            else:
                for mandate in payment.party.sepa_mandates:
                    if mandate.is_valid:
                        break
                else:
                    mandate = None
            mandates.append(mandate)
        return mandates

    def get_sepa_end_to_end_id(self, name):
        return str(self.id)

    @classmethod
    def search_end_to_end_id(cls, name, domain):
        table = cls.__table__()
        _, operator, value = domain
        cast = cls.sepa_end_to_end_id.sql_type().base
        Operator = fields.SQL_OPERATORS[operator]
        query = table.select(table.id,
            where=Operator(table.id.cast(cast), value))
        return [('id', 'in', query)]

    get_sepa_instruction_id = get_sepa_end_to_end_id
    search_sepa_instruction_id = search_end_to_end_id

    @property
    def sepa_remittance_information(self):
        if self.description:
            return self.description
        elif self.line and self.line.origin:
            return self.line.origin.rec_name

    @property
    def sepa_bank_account_number(self):
        if self.kind == 'receivable':
            if self.sepa_mandate:
                return self.sepa_mandate.account_number
        else:
            for account in self.party.bank_accounts:
                for number in account.numbers:
                    if number.type == 'iban':
                        return number

    @property
    def rejected(self):
        return (self.state == 'failed'
            and self.sepa_return_reason_code
            and self.sepa_return_reason_information == '/RTYP/RJCT')

    def create_clearing_move(self, date=None):
        if not date:
            date = Transaction().context.get('date_value')
        return super(Payment, self).create_clearing_move(date=date)


class Mandate(Workflow, ModelSQL, ModelView):
    'SEPA Mandate'
    __name__ = 'account.payment.sepa.mandate'
    party = fields.Many2One('party.party', 'Party', required=True, select=True,
        states={
            'readonly': Eval('state').in_(
                ['requested', 'validated', 'canceled']),
            },
        depends=['state'])
    account_number = fields.Many2One('bank.account.number', 'Account Number',
        ondelete='RESTRICT',
        states={
            'readonly': Eval('state').in_(['validated', 'canceled']),
            'required': Eval('state') == 'validated',
            },
        domain=[
            ('type', '=', 'iban'),
            ('account.owners', '=', Eval('party')),
            ],
        depends=['state', 'party'])
    identification = fields.Char('Identification', size=35,
        states={
            'readonly': Eval('identification_readonly', True),
            'required': Eval('state') == 'validated',
            },
        depends=['state', 'identification_readonly'])
    identification_readonly = fields.Function(fields.Boolean(
            'Identification Readonly'), 'get_identification_readonly')
    company = fields.Many2One('company.company', 'Company', required=True,
        select=True,
        domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ],
        states={
            'readonly': Eval('state') != 'draft',
            },
        depends=['state'])
    type = fields.Selection([
            ('recurrent', 'Recurrent'),
            ('one-off', 'One-off'),
            ], 'Type',
        states={
            'readonly': Eval('state').in_(['validated', 'canceled']),
            },
        depends=['state'])
    scheme = fields.Selection([
            ('CORE', 'Core'),
            ('B2B', 'Business to Business'),
            ], 'Scheme', required=True,
        states={
            'readonly': Eval('state').in_(['validated', 'canceled']),
            },
        depends=['state'])
    scheme_string = scheme.translated('scheme')
    signature_date = fields.Date('Signature Date',
        states={
            'readonly': Eval('state').in_(['validated', 'canceled']),
            'required': Eval('state') == 'validated',
            },
        depends=['state'])
    state = fields.Selection([
            ('draft', 'Draft'),
            ('requested', 'Requested'),
            ('validated', 'Validated'),
            ('canceled', 'Canceled'),
            ], 'State', readonly=True)
    payments = fields.One2Many('account.payment', 'sepa_mandate', 'Payments')
    has_payments = fields.Function(fields.Boolean('Has Payments'),
        'has_payments')

    @classmethod
    def __setup__(cls):
        super(Mandate, cls).__setup__()
        cls._transitions |= set((
                ('draft', 'requested'),
                ('requested', 'validated'),
                ('validated', 'canceled'),
                ('requested', 'canceled'),
                ('requested', 'draft'),
                ))
        cls._buttons.update({
                'cancel': {
                    'invisible': ~Eval('state').in_(
                        ['requested', 'validated']),
                    },
                'draft': {
                    'invisible': Eval('state') != 'requested',
                    },
                'request': {
                    'invisible': Eval('state') != 'draft',
                    },
                'validate_mandate': {
                    'invisible': Eval('state') != 'requested',
                    },
                })
        t = cls.__table__()
        cls._sql_constraints = [
            ('identification_unique', Unique(t, t.company, t.identification),
                'The identification of the SEPA mandate must be unique '
                'in a company.'),
            ]
        cls._error_messages.update({
                'delete_draft_canceled': ('You can not delete mandate "%s" '
                    'because it is not in draft or canceled state.'),
                })

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_type():
        return 'recurrent'

    @staticmethod
    def default_scheme():
        return 'CORE'

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_identification_readonly():
        pool = Pool()
        Configuration = pool.get('account.configuration')
        config = Configuration(1)
        return bool(config.sepa_mandate_sequence)

    def get_identification_readonly(self, name):
        return bool(self.identification)

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Sequence = pool.get('ir.sequence')
        Configuration = pool.get('account.configuration')

        config = Configuration(1)
        vlist = [v.copy() for v in vlist]
        for values in vlist:
            if (config.sepa_mandate_sequence
                    and not values.get('identification')):
                values['identification'] = Sequence.get_id(
                    config.sepa_mandate_sequence.id)
            # Prevent raising false unique constraint
            if values.get('identification') == '':
                values['identification'] = None
        return super(Mandate, cls).create(vlist)

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        args = []
        for mandates, values in zip(actions, actions):
            # Prevent raising false unique constraint
            if values.get('identification') == '':
                values = values.copy()
                values['identification'] = None
            args.extend((mandates, values))
        super(Mandate, cls).write(*args)

    @classmethod
    def copy(cls, mandates, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('state', 'draft')
        default.setdefault('payments', [])
        default.setdefault('signature_date', None)
        default.setdefault('identification', None)
        return super(Mandate, cls).copy(mandates, default=default)

    @property
    def is_valid(self):
        if self.state == 'validated':
            if self.type == 'one-off':
                if not self.has_payments:
                    return True
            else:
                return True
        return False

    @property
    def sequence_type(self):
        if self.type == 'one-off':
            return 'OOFF'
        elif (not self.payments
                or all(not p.sepa_mandate_sequence_type for p in self.payments)
                or all(p.rejected for p in self.payments)):
            return 'FRST'
        # TODO manage FNAL
        else:
            return 'RCUR'

    @classmethod
    def has_payments(self, mandates, name):
        pool = Pool()
        Payment = pool.get('account.payment')
        payment = Payment.__table__
        cursor = Transaction().cursor

        has_payments = dict.fromkeys([m.id for m in mandates], False)
        for sub_ids in grouped_slice(mandates):
            red_sql = reduce_ids(payment.sepa_mandate, sub_ids)
            cursor.execute(*payment.select(payment.sepa_mandate, Literal(True),
                    where=red_sql,
                    group_by=payment.sepa_mandate))
            has_payments.update(cursor.fetchall())

        return {'has_payments': has_payments}

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, mandates):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('requested')
    def request(cls, mandates):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('validated')
    def validate_mandate(cls, mandates):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('canceled')
    def cancel(cls, mandates):
        # TODO must be automaticaly canceled 13 months after last collection
        pass

    @classmethod
    def delete(cls, mandates):
        for mandate in mandates:
            if mandate.state not in ('draft', 'canceled'):
                cls.raise_user_error('delete_draft_canceled', mandate.rec_name)
        super(Mandate, cls).delete(mandates)


class MandateReport(CompanyReport):
    __name__ = 'account.payment.sepa.mandate'


class Message(Workflow, ModelSQL, ModelView):
    'SEPA Message'
    __name__ = 'account.payment.sepa.message'
    _states = {
        'readonly': Eval('state') != 'draft',
        }
    _depends = ['state']
    message = fields.Text('Message', states=_states, depends=_depends)
    filename = fields.Function(fields.Char('Filename'), 'get_filename')
    type = fields.Selection([
            ('in', 'IN'),
            ('out', 'OUT'),
            ], 'Type', required=True, states=_states, depends=_depends)
    company = fields.Many2One('company.company', 'Company', required=True,
        select=True,
        domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ],
        states={
            'readonly': Eval('state') != 'draft',
            },
        depends=['state'])
    origin = fields.Reference('Origin', selection='get_origin', select=True,
        states=_states, depends=_depends)
    state = fields.Selection([
            ('draft', 'Draft'),
            ('waiting', 'Waiting'),
            ('done', 'Done'),
            ('canceled', 'Canceled'),
            ], 'State', readonly=True, select=True)

    @classmethod
    def __setup__(cls):
        super(Message, cls).__setup__()
        cls._transitions |= {
            ('draft', 'waiting'),
            ('waiting', 'done'),
            ('waiting', 'draft'),
            ('draft', 'canceled'),
            ('waiting', 'canceled'),
            }
        cls._buttons.update({
                'cancel': {
                    'invisible': ~Eval('state').in_(['draft', 'waiting']),
                    },
                'draft': {
                    'invisible': Eval('state') != 'waiting',
                    },
                'wait': {
                    'invisible': Eval('state') != 'draft',
                    },
                'do': {
                    'invisible': Eval('state') != 'waiting',
                    },
                })

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().cursor
        pool = Pool()
        Group = pool.get('account.payment.group')

        super(Message, cls).__register__(module_name)

        # Migration from 3.2
        if TableHandler.table_exist(cursor, Group._table):
            group_table = TableHandler(cursor, Group, module_name)
            if group_table.column_exist('sepa_message'):
                group = Group.__table__()
                table = cls.__table__()
                cursor.execute(*group.select(
                        group.id, group.sepa_message, group.company))
                for group_id, message, company_id in cursor.fetchall():
                    cursor.execute(*table.insert(
                            [table.message, table.type, table.company,
                                table.origin, table.state],
                            [[message, 'out', company_id,
                                    'account.payment.group,%s' % group_id,
                                    'done']]))
                group_table.drop_column('sepa_message')

    @staticmethod
    def default_type():
        return 'in'

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_state():
        return 'draft'

    def get_filename(self, name):
        pool = Pool()
        Group = pool.get('account.payment.group')
        if isinstance(self.origin, Group):
            return self.origin.rec_name + '.xml'

    @staticmethod
    def _get_origin():
        'Return list of Model names for origin Reference'
        return ['account.payment.group']

    @classmethod
    def get_origin(cls):
        IrModel = Pool().get('ir.model')
        models = cls._get_origin()
        models = IrModel.search([
                ('model', 'in', models),
                ])
        return [(None, '')] + [(m.model, m.name) for m in models]

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, messages):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('waiting')
    def wait(cls, messages):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def do(cls, messages):
        for message in messages:
            if message.type == 'in':
                message.parse()
            else:
                message.send()

    @classmethod
    @ModelView.button
    @Workflow.transition('canceled')
    def cancel(cls, messages):
        pass

    @staticmethod
    def _get_handlers():
        pool = Pool()
        Payment = pool.get('account.payment')
        return {
            'urn:iso:std:iso:20022:tech:xsd:camt.054.001.01':
            lambda f: CAMT054(f, Payment),
            'urn:iso:std:iso:20022:tech:xsd:camt.054.001.02':
            lambda f: CAMT054(f, Payment),
            'urn:iso:std:iso:20022:tech:xsd:camt.054.001.03':
            lambda f: CAMT054(f, Payment),
            'urn:iso:std:iso:20022:tech:xsd:camt.054.001.04':
            lambda f: CAMT054(f, Payment),
            }

    @staticmethod
    def get_namespace(message):
        f = BytesIO(message)
        for _, element in etree.iterparse(f, events=('start',)):
            tag = etree.QName(element)
            if tag.localname == 'Document':
                return tag.namespace

    def parse(self):
        message = self.message.encode('utf-8')
        f = BytesIO(message)
        namespace = self.get_namespace(message)
        handlers = self._get_handlers()
        if namespace not in handlers:
            raise  # TODO UserError
        handlers[namespace](f)

    def send(self):
        pass
