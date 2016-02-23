# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from itertools import groupby

from trytond.model import Workflow, ModelView, ModelSQL, fields
from trytond.pyson import Eval, If
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateView, StateAction, Button
from trytond.pool import Pool

__all__ = ['Journal', 'Group', 'Payment',
    'ProcessPaymentStart', 'ProcessPayment']

KINDS = [
    ('payable', 'Payable'),
    ('receivable', 'Receivable'),
    ]


class Journal(ModelSQL, ModelView):
    'Payment Journal'
    __name__ = 'account.payment.journal'
    name = fields.Char('Name', required=True)
    currency = fields.Many2One('currency.currency', 'Currency', required=True)
    company = fields.Many2One('company.company', 'Company', required=True,
        select=True)
    process_method = fields.Selection([
            ('manual', 'Manual'),
            ], 'Process Method', required=True)

    @staticmethod
    def default_currency():
        if Transaction().context.get('company'):
            Company = Pool().get('company.company')
            company = Company(Transaction().context['company'])
            return company.currency.id

    @staticmethod
    def default_company():
        return Transaction().context.get('company')


class Group(ModelSQL, ModelView):
    'Payment Group'
    __name__ = 'account.payment.group'
    _rec_name = 'reference'
    reference = fields.Char('Reference', required=True, readonly=True)
    company = fields.Many2One('company.company', 'Company', required=True,
        readonly=True, select=True, domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ])
    journal = fields.Many2One('account.payment.journal', 'Journal',
        required=True, readonly=True, domain=[
            ('company', '=', Eval('company', -1)),
            ],
        depends=['company'])
    kind = fields.Selection(KINDS, 'Kind', required=True, readonly=True)
    payments = fields.One2Many('account.payment', 'group', 'Payments',
        readonly=True)

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Sequence = pool.get('ir.sequence')

        vlist = [v.copy() for v in vlist]
        for values in vlist:
            if 'reference' not in values:
                values['reference'] = Sequence.get('account.payment.group')

        return super(Group, cls).create(vlist)

    @classmethod
    def copy(cls, groups, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('payments', None)
        return super(Group, cls).copy(groups, default=default)

_STATES = {
    'readonly': Eval('state') != 'draft',
    }
_DEPENDS = ['state']


class Payment(Workflow, ModelSQL, ModelView):
    'Payment'
    __name__ = 'account.payment'
    company = fields.Many2One('company.company', 'Company', required=True,
        select=True, states=_STATES, domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ],
        depends=_DEPENDS)
    journal = fields.Many2One('account.payment.journal', 'Journal',
        required=True, states=_STATES, domain=[
            ('company', '=', Eval('company', -1)),
            ],
        depends=_DEPENDS + ['company'])
    currency = fields.Function(fields.Many2One('currency.currency',
            'Currency'), 'on_change_with_currency')
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    kind = fields.Selection(KINDS, 'Kind', required=True,
        states=_STATES, depends=_DEPENDS)
    party = fields.Many2One('party.party', 'Party', required=True,
        states=_STATES, depends=_DEPENDS)
    date = fields.Date('Date', required=True, states=_STATES, depends=_DEPENDS)
    amount = fields.Numeric('Amount', required=True,
        digits=(16, Eval('currency_digits', 2)), states=_STATES,
        depends=_DEPENDS + ['currency_digits'])
    line = fields.Many2One('account.move.line', 'Line', ondelete='RESTRICT',
        domain=[
            ('move.company', '=', Eval('company', -1)),
            If(Eval('kind') == 'receivable',
                ['OR', ('debit', '>', 0), ('credit', '<', 0)],
                ['OR', ('credit', '>', 0), ('debit', '<', 0)],
                ),
            ('account.kind', 'in', ['receivable', 'payable']),
            ('party', '=', Eval('party', None)),
            If(Eval('state') == 'draft',
                [
                    ('reconciliation', '=', None),
                    ],
                []),
            ['OR',
                ('second_currency', '=', Eval('currency', None)),
                [
                    ('account.company.currency', '=', Eval('currency', None)),
                    ('second_currency', '=', None),
                    ],
                ],
            ('move_state', '=', 'posted'),
            ],
        states=_STATES, depends=_DEPENDS + ['party', 'currency', 'kind',
            'company'])
    description = fields.Char('Description', states=_STATES, depends=_DEPENDS)
    group = fields.Many2One('account.payment.group', 'Group', readonly=True,
        ondelete='RESTRICT',
        states={
            'required': Eval('state').in_(['processing', 'succeeded']),
            },
        domain=[
            ('company', '=', Eval('company', -1)),
            ],
        depends=['state', 'company'])
    state = fields.Selection([
            ('draft', 'Draft'),
            ('approved', 'Approved'),
            ('processing', 'Processing'),
            ('succeeded', 'Succeeded'),
            ('failed', 'Failed'),
            ], 'State', readonly=True, select=True)

    @classmethod
    def __setup__(cls):
        super(Payment, cls).__setup__()
        cls._order.insert(0, ('date', 'DESC'))
        cls._error_messages.update({
                'delete_draft': ('Payment "%s" must be in draft before '
                    'deletion.'),
                })
        cls._transitions |= set((
                ('draft', 'approved'),
                ('approved', 'processing'),
                ('processing', 'succeeded'),
                ('processing', 'failed'),
                ('approved', 'draft'),
                ('succeeded', 'failed'),
                ('failed', 'succeeded'),
                ))
        cls._buttons.update({
                'draft': {
                    'invisible': Eval('state') != 'approved',
                    'icon': 'tryton-go-previous',
                    },
                'approve': {
                    'invisible': Eval('state') != 'draft',
                    'icon': 'tryton-go-next',
                    },
                'succeed': {
                    'invisible': ~Eval('state').in_(
                        ['processing', 'failed']),
                    'icon': 'tryton-ok',
                    },
                'fail': {
                    'invisible': ~Eval('state').in_(
                        ['processing', 'succeeded']),
                    'icon': 'tryton-cancel',
                    },
                })

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_kind():
        return 'payable'

    @staticmethod
    def default_date():
        pool = Pool()
        Date = pool.get('ir.date')
        return Date.today()

    @staticmethod
    def default_state():
        return 'draft'

    @fields.depends('journal')
    def on_change_with_currency(self, name=None):
        if self.journal:
            return self.journal.currency.id

    @fields.depends('journal')
    def on_change_with_currency_digits(self, name=None):
        if self.journal:
            return self.journal.currency.digits
        return 2

    @fields.depends('kind')
    def on_change_kind(self):
        self.line = None

    @fields.depends('party')
    def on_change_party(self):
        self.line = None

    @fields.depends('line')
    def on_change_line(self):
        if self.line:
            self.date = self.line.maturity_date
            self.amount = self.line.payment_amount

    @classmethod
    def delete(cls, payments):
        for payment in payments:
            if payment.state != 'draft':
                cls.raise_user_error('delete_draft', (payment.rec_name))
        super(Payment, cls).delete(payments)

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, payments):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('approved')
    def approve(cls, payments):
        pass

    @classmethod
    @Workflow.transition('processing')
    def process(cls, payments, group):
        pool = Pool()
        Group = pool.get('account.payment.group')
        if payments:
            group = group()
            cls.write(payments, {
                    'group': group.id,
                    })
            process_method = getattr(Group,
                'process_%s' % group.journal.process_method, None)
            if process_method:
                process_method(group)
                group.save()
            return group

    @classmethod
    @ModelView.button
    @Workflow.transition('succeeded')
    def succeed(cls, payments):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('failed')
    def fail(cls, payments):
        pass


class ProcessPaymentStart(ModelView):
    'Process Payment'
    __name__ = 'account.payment.process.start'


class ProcessPayment(Wizard):
    'Process Payment'
    __name__ = 'account.payment.process'
    start = StateView('account.payment.process.start',
        'account_payment.payment_process_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Process', 'process', 'tryton-ok', default=True),
            ])
    process = StateAction('account_payment.act_payment_group_form')

    @classmethod
    def __setup__(cls):
        super(ProcessPayment, cls).__setup__()
        cls._error_messages.update({
                'overpay': 'The Payment "%(payment)s" overpays '
                'the Line "%(line)s".',
                })

    def _group_payment_key(self, payment):
        return (('journal', payment.journal.id), ('kind', payment.kind))

    def _new_group(self, values):
        pool = Pool()
        Group = pool.get('account.payment.group')
        return Group(**values)

    def do_process(self, action):
        pool = Pool()
        Payment = pool.get('account.payment')
        payments = Payment.browse(Transaction().context['active_ids'])

        for payment in payments:
            if payment.line and payment.line.payment_amount < 0:
                self.raise_user_warning(str(payment),
                    'overpay', {
                        'payment': payment.rec_name,
                        'line': payment.line.rec_name,
                        })

        groups = []
        payments = sorted(payments, key=self._group_payment_key)
        for key, grouped_payments in groupby(payments,
                key=self._group_payment_key):
            def group():
                group = self._new_group(dict(key))
                group.save()
                groups.append(group)
                return group
            Payment.process(list(grouped_payments), group)

        return action, {
            'res_id': [g.id for g in groups],
            }
