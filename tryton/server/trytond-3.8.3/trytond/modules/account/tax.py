# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import datetime
from collections import namedtuple
from decimal import Decimal
from itertools import groupby

from sql import Null
from sql.aggregate import Sum
from sql.conditionals import Case

from trytond.model import ModelView, ModelSQL, MatchMixin, fields
from trytond.wizard import Wizard, StateView, StateAction, Button
from trytond import backend
from trytond.pyson import Eval, If, Bool, PYSONEncoder
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta

__all__ = ['TaxGroup', 'TaxCodeTemplate', 'TaxCode',
    'OpenChartTaxCodeStart', 'OpenChartTaxCode',
    'TaxTemplate', 'Tax', 'TaxLine', 'TaxRuleTemplate', 'TaxRule',
    'TaxRuleLineTemplate', 'TaxRuleLine',
    'OpenTaxCode',
    'AccountTemplateTaxTemplate', 'AccountTemplate2', 'AccountTax', 'Account2']
__metaclass__ = PoolMeta

KINDS = [
    ('sale', 'Sale'),
    ('purchase', 'Purchase'),
    ('both', 'Both'),
    ]


class TaxGroup(ModelSQL, ModelView):
    'Tax Group'
    __name__ = 'account.tax.group'
    name = fields.Char('Name', size=None, required=True)
    code = fields.Char('Code', size=None, required=True)
    kind = fields.Selection(KINDS, 'Kind', required=True)

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        super(TaxGroup, cls).__register__(module_name)
        cursor = Transaction().cursor
        table = TableHandler(cursor, cls, module_name)

        # Migration from 1.4 drop code_uniq constraint
        table.drop_constraint('code_uniq')

    @staticmethod
    def default_kind():
        return 'both'


class TaxCodeTemplate(ModelSQL, ModelView):
    'Tax Code Template'
    __name__ = 'account.tax.code.template'
    name = fields.Char('Name', required=True)
    code = fields.Char('Code')
    parent = fields.Many2One('account.tax.code.template', 'Parent')
    childs = fields.One2Many('account.tax.code.template', 'parent', 'Children')
    account = fields.Many2One('account.account.template', 'Account Template',
            domain=[('parent', '=', None)], required=True)
    description = fields.Text('Description')

    @classmethod
    def __setup__(cls):
        super(TaxCodeTemplate, cls).__setup__()
        cls._order.insert(0, ('code', 'ASC'))
        cls._order.insert(0, ('account', 'ASC'))

    @classmethod
    def validate(cls, templates):
        super(TaxCodeTemplate, cls).validate(templates)
        cls.check_recursion(templates)

    def _get_tax_code_value(self, code=None):
        '''
        Set values for tax code creation.
        '''
        res = {}
        if not code or code.name != self.name:
            res['name'] = self.name
        if not code or code.code != self.code:
            res['code'] = self.code
        if not code or code.description != self.description:
            res['description'] = self.description
        if not code or code.template.id != self.id:
            res['template'] = self.id
        return res

    def create_tax_code(self, company_id, template2tax_code=None,
            parent_id=None):
        '''
        Create recursively tax codes based on template.
        template2tax_code is a dictionary with tax code template id as key and
        tax code id as value, used to convert template id into tax code. The
        dictionary is filled with new tax codes.
        Return the id of the tax code created
        '''
        pool = Pool()
        TaxCode = pool.get('account.tax.code')

        if template2tax_code is None:
            template2tax_code = {}

        if self.id not in template2tax_code:
            vals = self._get_tax_code_value()
            vals['company'] = company_id
            vals['parent'] = parent_id

            new_tax_code, = TaxCode.create([vals])

            prev_data = {}
            for field_name, field in self._fields.iteritems():
                prev_data[field_name] = getattr(self, field_name)
            template2tax_code[self.id] = new_tax_code.id
        new_id = template2tax_code[self.id]

        new_childs = []
        for child in self.childs:
            new_childs.append(child.create_tax_code(company_id,
                    template2tax_code=template2tax_code, parent_id=new_id))
        return new_id


class TaxCode(ModelSQL, ModelView):
    'Tax Code'
    __name__ = 'account.tax.code'
    name = fields.Char('Name', size=None, required=True, select=True)
    code = fields.Char('Code', size=None, select=True)
    active = fields.Boolean('Active', select=True)
    company = fields.Many2One('company.company', 'Company', required=True,
        select=True)
    parent = fields.Many2One('account.tax.code', 'Parent', select=True,
            domain=[('company', '=', Eval('company', 0))], depends=['company'])
    childs = fields.One2Many('account.tax.code', 'parent', 'Children',
            domain=[('company', '=', Eval('company', 0))], depends=['company'])
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    sum = fields.Function(fields.Numeric('Sum',
        digits=(16, Eval('currency_digits', 2)), depends=['currency_digits']),
        'get_sum')
    template = fields.Many2One('account.tax.code.template', 'Template')
    description = fields.Text('Description')

    @classmethod
    def __setup__(cls):
        super(TaxCode, cls).__setup__()
        cls._order.insert(0, ('code', 'ASC'))

    @classmethod
    def validate(cls, codes):
        super(TaxCode, cls).validate(codes)
        cls.check_recursion(codes)

    @staticmethod
    def default_active():
        return True

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @fields.depends('company')
    def on_change_with_currency_digits(self, name=None):
        if self.company:
            return self.company.currency.digits
        return 2

    @classmethod
    def get_sum(cls, codes, name):
        cursor = Transaction().cursor
        res = {}
        pool = Pool()
        MoveLine = pool.get('account.move.line')
        TaxLine = pool.get('account.tax.line')

        code = cls.__table__()
        tax_line = TaxLine.__table__()
        move_line = MoveLine.__table__()

        childs = cls.search([
                ('parent', 'child_of', [c.id for c in codes]),
                ])
        all_codes = list(set(codes) | set(childs))
        line_query, _ = MoveLine.query_get(move_line)
        cursor.execute(*code.join(tax_line, condition=tax_line.code == code.id
                ).join(move_line, condition=tax_line.move_line == move_line.id
                ).select(code.id, Sum(tax_line.amount),
                where=code.id.in_([c.id for c in all_codes])
                & (code.active == True) & line_query,
                group_by=code.id))
        code_sum = {}
        for code_id, sum in cursor.fetchall():
            # SQLite uses float for SUM
            if not isinstance(sum, Decimal):
                sum = Decimal(str(sum))
            code_sum[code_id] = sum

        for code in codes:
            res.setdefault(code.id, Decimal('0.0'))
            childs = cls.search([
                    ('parent', 'child_of', [code.id]),
                    ])
            for child in childs:
                res[code.id] += code.company.currency.round(
                    code_sum.get(child.id, Decimal('0.0')))
            res[code.id] = code.company.currency.round(res[code.id])
        return res

    def get_rec_name(self, name):
        if self.code:
            return self.code + ' - ' + self.name
        else:
            return self.name

    @classmethod
    def search_rec_name(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'
        return [bool_op,
            ('code',) + tuple(clause[1:]),
            (cls._rec_name,) + tuple(clause[1:]),
            ]

    @classmethod
    def delete(cls, codes):
        codes = cls.search([
                ('parent', 'child_of', [c.id for c in codes]),
                ])
        super(TaxCode, cls).delete(codes)

    def update_tax_code(self, template2tax_code=None):
        '''
        Update recursively tax code based on template.
        template2tax_code is a dictionary with tax code template id as key and
        tax code id as value, used to convert template id into tax code. The
        dictionary is filled with new tax codes
        '''

        if template2tax_code is None:
            template2tax_code = {}

        if self.template:
            vals = self.template._get_tax_code_value(code=self)
            if vals:
                self.write([self], vals)
            template2tax_code[self.template.id] = self.id

        for child in self.childs:
            child.update_tax_code(template2tax_code=template2tax_code)


class OpenChartTaxCodeStart(ModelView):
    'Open Chart of Tax Codes'
    __name__ = 'account.tax.code.open_chart.start'
    method = fields.Selection([
        ('fiscalyear', 'By Fiscal Year'),
        ('periods', 'By Periods'),
        ], 'Method', required=True)
    fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal Year',
        help='Leave empty for all open fiscal year',
        states={
            'invisible': Eval('method') != 'fiscalyear',
            }, depends=['method'])
    periods = fields.Many2Many('account.period', None, None, 'Periods',
        help='Leave empty for all periods of all open fiscal year',
        states={
            'invisible': Eval('method') != 'periods',
            }, depends=['method'])

    @staticmethod
    def default_method():
        return 'periods'


class OpenChartTaxCode(Wizard):
    'Open Chart of Tax Codes'
    __name__ = 'account.tax.code.open_chart'
    start = StateView('account.tax.code.open_chart.start',
        'account.tax_code_open_chart_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Open', 'open_', 'tryton-ok', default=True),
            ])
    open_ = StateAction('account.act_tax_code_tree2')

    def do_open_(self, action):
        if self.start.method == 'fiscalyear':
            action['pyson_context'] = PYSONEncoder().encode({
                    'fiscalyear': (self.start.fiscalyear.id
                        if self.start.fiscalyear else None),
                    })
            if self.start.fiscalyear:
                action['name'] += ' - %s' % self.start.fiscalyear.rec_name
        else:
            action['pyson_context'] = PYSONEncoder().encode({
                    'periods': [x.id for x in self.start.periods],
                    })
            period_str = ', '.join(p.rec_name for p in self.start.periods)
            if period_str:
                action['name'] += ' (%s)' % period_str
        return action, {}

    def transition_open_(self):
        return 'end'


class TaxTemplate(ModelSQL, ModelView):
    'Account Tax Template'
    __name__ = 'account.tax.template'
    name = fields.Char('Name', required=True)
    description = fields.Char('Description', required=True)
    group = fields.Many2One('account.tax.group', 'Group')
    sequence = fields.Integer('Sequence')
    start_date = fields.Date('Starting Date')
    end_date = fields.Date('Ending Date')
    amount = fields.Numeric('Amount', digits=(16, 8),
        states={
            'required': Eval('type') == 'fixed',
            'invisible': Eval('type') != 'fixed',
            },
        depends=['type'])
    rate = fields.Numeric('Rate', digits=(14, 10),
        states={
            'required': Eval('type') == 'percentage',
            'invisible': Eval('type') != 'percentage',
            }, depends=['type'])
    type = fields.Selection([
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed'),
        ('none', 'None'),
        ], 'Type', required=True)
    update_unit_price = fields.Boolean('Update Unit Price',
        states={
            'invisible': Bool(Eval('parent')),
            },
        depends=['parent'])
    parent = fields.Many2One('account.tax.template', 'Parent')
    childs = fields.One2Many('account.tax.template', 'parent', 'Children')
    invoice_account = fields.Many2One('account.account.template',
            'Invoice Account')
    credit_note_account = fields.Many2One('account.account.template',
            'Credit Note Account')
    invoice_base_code = fields.Many2One('account.tax.code.template',
            'Invoice Base Code')
    invoice_base_sign = fields.Numeric('Invoice Base Sign', digits=(2, 0))
    invoice_tax_code = fields.Many2One('account.tax.code.template',
            'Invoice Tax Code')
    invoice_tax_sign = fields.Numeric('Invoice Tax Sign', digits=(2, 0))
    credit_note_base_code = fields.Many2One('account.tax.code.template',
            'Credit Note Base Code')
    credit_note_base_sign = fields.Numeric('Credit Note Base Sign',
        digits=(2, 0))
    credit_note_tax_code = fields.Many2One('account.tax.code.template',
            'Credit Note Tax Code')
    credit_note_tax_sign = fields.Numeric('Credit Note Tax Sign',
        digits=(2, 0))
    account = fields.Many2One('account.account.template', 'Account Template',
            domain=[('parent', '=', None)], required=True)

    @classmethod
    def __setup__(cls):
        super(TaxTemplate, cls).__setup__()
        cls._order.insert(0, ('sequence', 'ASC'))
        cls._order.insert(0, ('account', 'ASC'))
        cls._error_messages.update({
                'update_unit_price_with_parent': ('"Update Unit Price" can '
                    'not be set on tax "%(template)s" which has a parent.'),
                })

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        super(TaxTemplate, cls).__register__(module_name)
        cursor = Transaction().cursor
        table = TableHandler(cursor, cls, module_name)

        # Migration from 1.0 group is no more required
        table.not_null_action('group', action='remove')

        # Migration from 2.4: drop required on sequence
        table.not_null_action('sequence', action='remove')

        # Migration from 2.8: rename percentage into rate
        if table.column_exist('percentage'):
            sql_table = cls.__table__()
            cursor.execute(*sql_table.update(
                    columns=[sql_table.rate],
                    values=[sql_table.percentage / 100]))
            table.drop_column('percentage')

    @classmethod
    def validate(cls, tax_templates):
        super(TaxTemplate, cls).validate(tax_templates)
        for tax_template in tax_templates:
            tax_template.check_update_unit_price()

    def check_update_unit_price(self):
        if self.update_unit_price and self.parent:
            self.raise_user_error('update_unit_price_with_parent', {
                    'template': self.rec_name,
                    })

    @staticmethod
    def order_sequence(tables):
        table, _ = tables[None]
        return [Case((table.sequence == Null, 0), else_=1), table.sequence]

    @staticmethod
    def default_type():
        return 'percentage'

    @staticmethod
    def default_invoice_base_sign():
        return Decimal('1')

    @staticmethod
    def default_invoice_tax_sign():
        return Decimal('1')

    @staticmethod
    def default_credit_note_base_sign():
        return Decimal('1')

    @staticmethod
    def default_credit_note_tax_sign():
        return Decimal('1')

    @staticmethod
    def default_update_unit_price():
        return False

    def _get_tax_value(self, tax=None):
        '''
        Set values for tax creation.
        '''
        res = {}
        for field in ('name', 'description', 'sequence', 'amount',
                'rate', 'type', 'invoice_base_sign', 'invoice_tax_sign',
                'credit_note_base_sign', 'credit_note_tax_sign',
                'start_date', 'end_date', 'update_unit_price'):
            if not tax or getattr(tax, field) != getattr(self, field):
                res[field] = getattr(self, field)
        for field in ('group',):
            if not tax or getattr(tax, field) != getattr(self, field):
                value = getattr(self, field)
                if value:
                    res[field] = getattr(self, field).id
                else:
                    res[field] = None
        if not tax or tax.template != self:
            res['template'] = self.id
        return res

    def create_tax(self, company_id, template2tax_code, template2account,
            template2tax=None, parent_id=None):
        '''
        Create recursively taxes based on template.

        template2tax_code is a dictionary with tax code template id as key and
        tax code id as value, used to convert tax code template into tax code.
        template2account is a dictionary with account template id as key and
        account id as value, used to convert account template into account
        code.
        template2tax is a dictionary with tax template id as key and tax id as
        value, used to convert template id into tax.  The dictionary is filled
        with new taxes.
        Return id of the tax created
        '''
        pool = Pool()
        Tax = pool.get('account.tax')

        if template2tax is None:
            template2tax = {}

        if self.id not in template2tax:
            vals = self._get_tax_value()
            vals['company'] = company_id
            vals['parent'] = parent_id
            if self.invoice_account:
                vals['invoice_account'] = \
                    template2account[self.invoice_account.id]
            else:
                vals['invoice_account'] = None
            if self.credit_note_account:
                vals['credit_note_account'] = \
                    template2account[self.credit_note_account.id]
            else:
                vals['credit_note_account'] = None
            if self.invoice_base_code:
                vals['invoice_base_code'] = \
                    template2tax_code[self.invoice_base_code.id]
            else:
                vals['invoice_base_code'] = None
            if self.invoice_tax_code:
                vals['invoice_tax_code'] = \
                    template2tax_code[self.invoice_tax_code.id]
            else:
                vals['invoice_tax_code'] = None
            if self.credit_note_base_code:
                vals['credit_note_base_code'] = \
                    template2tax_code[self.credit_note_base_code.id]
            else:
                vals['credit_note_base_code'] = None
            if self.credit_note_tax_code:
                vals['credit_note_tax_code'] = \
                    template2tax_code[self.credit_note_tax_code.id]
            else:
                vals['credit_note_tax_code'] = None

            new_tax, = Tax.create([vals])

            template2tax[self.id] = new_tax.id
        new_id = template2tax[self.id]

        new_childs = []
        for child in self.childs:
            new_childs.append(child.create_tax(company_id, template2tax_code,
                    template2account, template2tax=template2tax,
                    parent_id=new_id))
        return new_id


class Tax(ModelSQL, ModelView):
    '''
    Account Tax

    Type:
        percentage: tax = price * rate
        fixed: tax = amount
        none: tax = none
    '''
    __name__ = 'account.tax'
    name = fields.Char('Name', required=True)
    description = fields.Char('Description', required=True,
            help="The name that will be used in reports")
    group = fields.Many2One('account.tax.group', 'Group',
            states={
                'invisible': Bool(Eval('parent')),
            }, depends=['parent'])
    active = fields.Boolean('Active')
    sequence = fields.Integer('Sequence', help='Use to order the taxes')
    start_date = fields.Date('Starting Date')
    end_date = fields.Date('Ending Date')
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    amount = fields.Numeric('Amount', digits=(16, Eval('currency_digits', 2)),
        states={
            'required': Eval('type') == 'fixed',
            'invisible': Eval('type') != 'fixed',
            }, help='In company\'s currency',
        depends=['type', 'currency_digits'])
    rate = fields.Numeric('Rate', digits=(14, 10),
        states={
            'required': Eval('type') == 'percentage',
            'invisible': Eval('type') != 'percentage',
            }, depends=['type'])
    type = fields.Selection([
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed'),
        ('none', 'None'),
        ], 'Type', required=True)
    update_unit_price = fields.Boolean('Update Unit Price',
        states={
            'invisible': Bool(Eval('parent')),
            },
        depends=['parent'],
        help=('If checked then the unit price for further tax computation will'
            ' be modified by this tax'))
    parent = fields.Many2One('account.tax', 'Parent', ondelete='CASCADE')
    childs = fields.One2Many('account.tax', 'parent', 'Children')
    company = fields.Many2One('company.company', 'Company', required=True,
        domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ], select=True)
    invoice_account = fields.Many2One('account.account', 'Invoice Account',
        domain=[
            ('company', '=', Eval('company')),
            ('kind', 'not in', ['view', 'receivable', 'payable']),
            ],
        states={
            'readonly': (Eval('type') == 'none') | ~Eval('company'),
            'required': (Eval('type') != 'none') & Eval('company'),
            },
        depends=['company', 'type'])
    credit_note_account = fields.Many2One('account.account',
        'Credit Note Account',
        domain=[
            ('company', '=', Eval('company')),
            ('kind', 'not in', ['view', 'receivable', 'payable']),
            ],
        states={
            'readonly': (Eval('type') == 'none') | ~Eval('company'),
            'required': (Eval('type') != 'none') & Eval('company'),
            },
        depends=['company', 'type'])
    invoice_base_code = fields.Many2One('account.tax.code',
        'Invoice Base Code',
        domain=[
            ('company', '=', Eval('company', -1)),
            ],
        states={
            'readonly': Eval('type') == 'none',
            },
        depends=['type', 'company'])
    invoice_base_sign = fields.Numeric('Invoice Base Sign', digits=(2, 0),
        help='Usualy 1 or -1',
        states={
            'required': Eval('type') != 'none',
            'readonly': Eval('type') == 'none',
            }, depends=['type'])
    invoice_tax_code = fields.Many2One('account.tax.code',
        'Invoice Tax Code',
        domain=[
            ('company', '=', Eval('company', -1)),
            ],
        states={
            'readonly': Eval('type') == 'none',
            },
        depends=['type', 'company'])
    invoice_tax_sign = fields.Numeric('Invoice Tax Sign', digits=(2, 0),
        help='Usualy 1 or -1',
        states={
            'required': Eval('type') != 'none',
            'readonly': Eval('type') == 'none',
            }, depends=['type'])
    credit_note_base_code = fields.Many2One('account.tax.code',
        'Credit Note Base Code',
        domain=[
            ('company', '=', Eval('company', -1)),
            ],
        states={
            'readonly': Eval('type') == 'none',
            },
        depends=['type', 'company'])
    credit_note_base_sign = fields.Numeric('Credit Note Base Sign',
        digits=(2, 0), help='Usualy 1 or -1',
        states={
            'required': Eval('type') != 'none',
            'readonly': Eval('type') == 'none',
            }, depends=['type'])
    credit_note_tax_code = fields.Many2One('account.tax.code',
        'Credit Note Tax Code',
        domain=[
            ('company', '=', Eval('company', -1)),
            ],
        states={
            'readonly': Eval('type') == 'none',
            },
        depends=['type', 'company'])
    credit_note_tax_sign = fields.Numeric('Credit Note Tax Sign',
        digits=(2, 0), help='Usualy 1 or -1',
        states={
            'required': Eval('type') != 'none',
            'readonly': Eval('type') == 'none',
            }, depends=['type'])
    template = fields.Many2One('account.tax.template', 'Template')

    @classmethod
    def __setup__(cls):
        super(Tax, cls).__setup__()
        cls._order.insert(0, ('sequence', 'ASC'))
        cls._error_messages.update({
                'update_unit_price_with_parent': ('"Update Unit Price" can '
                    'not be set on tax "%(template)s" which has a parent.'),
                })

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        super(Tax, cls).__register__(module_name)
        cursor = Transaction().cursor
        table = TableHandler(cursor, cls, module_name)

        # Migration from 1.0 group is no more required
        table.not_null_action('group', action='remove')

        # Migration from 2.4: drop required on sequence
        table.not_null_action('sequence', action='remove')

        # Migration from 2.8: rename percentage into rate
        if table.column_exist('percentage'):
            sql_table = cls.__table__()
            cursor.execute(*sql_table.update(
                    columns=[sql_table.rate],
                    values=[sql_table.percentage / 100]))
            table.drop_column('percentage')

    @classmethod
    def validate(cls, taxes):
        super(Tax, cls).validate(taxes)
        for tax in taxes:
            tax.check_update_unit_price()

    def check_update_unit_price(self):
        if self.parent and self.update_unit_price:
            self.raise_user_error('update_unit_price_with_parent', {
                    'tax': self.rec_name,
                    })

    @staticmethod
    def order_sequence(tables):
        table, _ = tables[None]
        return [Case((table.sequence == Null, 0), else_=1), table.sequence]

    @staticmethod
    def default_active():
        return True

    @staticmethod
    def default_type():
        return 'percentage'

    @staticmethod
    def default_invoice_base_sign():
        return Decimal('1')

    @staticmethod
    def default_invoice_tax_sign():
        return Decimal('1')

    @staticmethod
    def default_credit_note_base_sign():
        return Decimal('1')

    @staticmethod
    def default_credit_note_tax_sign():
        return Decimal('1')

    @staticmethod
    def default_update_unit_price():
        return False

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @fields.depends('company')
    def on_change_with_currency_digits(self, name=None):
        if self.company:
            return self.company.currency.digits
        return 2

    def _process_tax(self, price_unit):
        if self.type == 'percentage':
            amount = price_unit * self.rate
            return {
                'base': price_unit,
                'amount': amount,
                'tax': self,
                }
        if self.type == 'fixed':
            amount = self.amount
            return {
                'base': price_unit,
                'amount': amount,
                'tax': self,
                }

    def _group_taxes(self):
        'Key method used to group taxes'
        return (self.sequence,)

    @classmethod
    def _unit_compute(cls, taxes, price_unit, date):
        res = []
        for _, group_taxes in groupby(taxes, key=cls._group_taxes):
            unit_price_variation = 0
            for tax in group_taxes:
                start_date = tax.start_date or datetime.date.min
                end_date = tax.end_date or datetime.date.max
                if not (start_date <= date <= end_date):
                    continue
                if tax.type != 'none':
                    value = tax._process_tax(price_unit)
                    res.append(value)
                    if tax.update_unit_price:
                        unit_price_variation += value['amount']
                if len(tax.childs):
                    res.extend(cls._unit_compute(tax.childs, price_unit, date))
            price_unit += unit_price_variation
        return res

    @classmethod
    def _reverse_rate_amount(cls, taxes, date):
        rate, amount = 0, 0
        for tax in taxes:
            start_date = tax.start_date or datetime.date.min
            end_date = tax.end_date or datetime.date.max
            if not (start_date <= date <= end_date):
                continue

            if tax.type == 'percentage':
                rate += tax.rate
            elif tax.type == 'fixed':
                amount += tax.amount

            if tax.childs:
                child_rate, child_amount = cls._reverse_rate_amount(
                    tax.childs, date)
                rate += child_rate
                amount += child_amount
        return rate, amount

    @classmethod
    def _reverse_unit_compute(cls, price_unit, taxes, date):
        rate, amount = 0, 0
        update_unit_price = False
        unit_price_variation_amount = 0
        unit_price_variation_rate = 0
        for _, group_taxes in groupby(taxes, key=cls._group_taxes):
            group_taxes = list(group_taxes)
            g_rate, g_amount = cls._reverse_rate_amount(group_taxes, date)
            if update_unit_price:
                g_amount += unit_price_variation_amount * g_rate
                g_rate += unit_price_variation_rate * g_rate

            g_update_unit_price = any(t.update_unit_price for t in group_taxes)
            update_unit_price |= g_update_unit_price
            if g_update_unit_price:
                unit_price_variation_amount += g_amount
                unit_price_variation_rate += g_rate

            rate += g_rate
            amount += g_amount

        return (price_unit - amount) / (1 + rate)

    @classmethod
    def sort_taxes(cls, taxes, reverse=False):
        '''
        Return a list of taxes sorted
        '''
        return sorted(taxes, key=lambda t: (t.sequence, t.id), reverse=reverse)

    @classmethod
    def compute(cls, taxes, price_unit, quantity, date=None):
        '''
        Compute taxes for price_unit and quantity at the date.
        Return list of dict for each taxes and their childs with:
            base
            amount
            tax
        '''
        pool = Pool()
        Date = pool.get('ir.date')
        if date is None:
            date = Date.today()
        taxes = cls.sort_taxes(taxes)
        res = cls._unit_compute(taxes, price_unit, date)
        quantity = Decimal(str(quantity or 0.0))
        for row in res:
            row['base'] *= quantity
            row['amount'] *= quantity
        return res

    @classmethod
    def reverse_compute(cls, price_unit, taxes, date=None):
        '''
        Reverse compute the price_unit for taxes at the date.
        '''
        pool = Pool()
        Date = pool.get('ir.date')
        if date is None:
            date = Date.today()
        taxes = cls.sort_taxes(taxes)
        return cls._reverse_unit_compute(price_unit, taxes, date)

    def update_tax(self, template2tax_code, template2account,
            template2tax=None):
        '''
        Update recursively taxes based on template.
        template2tax_code is a dictionary with tax code template id as key and
        tax code id as value, used to convert tax code template into tax code.
        template2account is a dictionary with account template id as key and
        account id as value, used to convert account template into account
        code.
        template2tax is a dictionary with tax template id as key and tax id as
        value, used to convert template id into tax.  The dictionary is filled
        with new taxes.
        '''

        if template2tax is None:
            template2tax = {}

        if self.template:
            vals = self.template._get_tax_value(tax=self)
            invoice_account_id = (self.invoice_account.id
                if self.invoice_account else None)
            if (self.template.invoice_account and
                    invoice_account_id != template2account.get(
                            self.template.invoice_account.id)):
                vals['invoice_account'] = template2account.get(
                    self.template.invoice_account.id)
            elif (not self.template.invoice_account
                    and self.invoice_account):
                vals['invoice_account'] = None
            credit_note_account_id = (self.credit_note_account.id
                if self.credit_note_account else None)
            if (self.template.credit_note_account and
                    credit_note_account_id != template2account.get(
                        self.template.credit_note_account.id)):
                vals['credit_note_account'] = template2account.get(
                    self.template.credit_note_account.id)
            elif (not self.template.credit_note_account
                    and self.credit_note_account):
                vals['credit_note_account'] = None
            invoice_base_code_id = (self.invoice_base_code.id
                if self.invoice_base_code else None)
            if (self.template.invoice_base_code and
                    invoice_base_code_id != template2tax_code.get(
                            self.template.invoice_base_code.id)):
                vals['invoice_base_code'] = template2tax_code.get(
                    self.template.invoice_base_code.id)
            elif (not self.template.invoice_base_code
                    and self.invoice_base_code):
                vals['invoice_base_code'] = None
            invoice_tax_code_id = (self.invoice_tax_code.id
                if self.invoice_tax_code else None)
            if (self.template.invoice_tax_code
                    and invoice_tax_code_id != template2tax_code.get(
                        self.template.invoice_tax_code.id)):
                vals['invoice_tax_code'] = template2tax_code.get(
                    self.template.invoice_tax_code.id)
            elif (not self.template.invoice_tax_code
                    and self.invoice_tax_code):
                vals['invoice_tax_code'] = None
            credit_note_base_code_id = (self.credit_note_base_code.id
                if self.credit_note_base_code else None)
            if (self.template.credit_note_base_code
                    and credit_note_base_code_id != template2tax_code.get(
                        self.template.credit_note_base_code.id)):
                vals['credit_note_base_code'] = template2tax_code.get(
                    self.template.credit_note_base_code.id)
            elif (not self.template.credit_note_base_code
                    and self.credit_note_base_code):
                vals['credit_note_base_code'] = None
            credit_note_tax_code_id = (self.credit_note_tax_code.id
                if self.credit_note_tax_code else None)
            if (self.template.credit_note_tax_code
                    and credit_note_tax_code_id != template2tax_code.get(
                        self.template.credit_note_tax_code.id)):
                vals['credit_note_tax_code'] = template2tax_code.get(
                    self.template.credit_note_tax_code.id)
            elif (not self.template.credit_note_tax_code
                    and self.credit_note_tax_code):
                vals['credit_note_tax_code'] = None

            if vals:
                self.write([self], vals)

            template2tax[self.template.id] = self.id

        for child in self.childs:
            child.update_tax(template2tax_code, template2account,
                template2tax=template2tax)


class _TaxKey(dict):

    def __init__(self, **kwargs):
        self.update(kwargs)

    def _key(self):
        return (self['base_code'], self['base_sign'],
            self['tax_code'], self['tax_sign'],
            self['account'], self['tax'])

    def __eq__(self, other):
        if isinstance(other, _TaxKey):
            return self._key() == other._key()
        return self._key() == other

    def __hash__(self):
        return hash(self._key())

_TaxableLine = namedtuple('_TaxableLine', ('taxes', 'unit_price', 'quantity'))


class TaxableMixin(object):

    @property
    def taxable_lines(self):
        """A list of tuples where
            - the first element is the taxes applicable
            - the second element is the line unit price
            - the third element is the line quantity
        """
        return []

    @property
    def tax_type(self):
        "The taxation type it can be 'invoice' or 'credit_note'"
        return None

    @property
    def currency(self):
        "The currency used by the taxable object"
        return None

    @property
    def tax_date(self):
        "Date to use when computing the tax"
        pool = Pool()
        Date = pool.get('ir.date')
        return Date.today()

    def _get_tax_context(self):
        return {}

    @staticmethod
    def _compute_tax_line(type_, amount, base, tax):
        assert type_ in ('invoice', 'credit_note')

        line = {}
        line['manual'] = False
        line['description'] = tax.description
        line['base'] = base
        line['amount'] = amount
        line['tax'] = tax.id if tax else None

        for attribute in ['base_code', 'tax_code', 'account']:
            value = getattr(tax, '%s_%s' % (type_, attribute), None)
            line[attribute] = value.id if value else None

        for attribute in ['base_sign', 'tax_sign']:
            value = getattr(tax, '%s_%s' % (type_, attribute), None)
            line[attribute] = value

        return _TaxKey(**line)

    def _round_taxes(self, taxes):
        if not self.currency:
            return
        for taxline in taxes.itervalues():
            for attribute in ('base', 'amount'):
                taxline[attribute] = self.currency.round(taxline[attribute])

    def _get_taxes(self):
        pool = Pool()
        Tax = pool.get('account.tax')
        Configuration = pool.get('account.configuration')

        config = Configuration(1)
        taxes = {}
        with Transaction().set_context(self._get_tax_context()):
            taxable_lines = [_TaxableLine(*params)
                for params in self.taxable_lines]
            for line in taxable_lines:
                l_taxes = Tax.compute(line.taxes, line.unit_price,
                    line.quantity, self.tax_date)
                for tax in l_taxes:
                    taxline = self._compute_tax_line(self.tax_type, **tax)
                    if taxline not in taxes:
                        taxes[taxline] = taxline
                    else:
                        taxes[taxline]['base'] += taxline['base']
                        taxes[taxline]['amount'] += taxline['amount']
                if config.tax_rounding == 'line':
                    self._round_taxes(taxes)
        if config.tax_rounding == 'document':
            self._round_taxes(taxes)
        return taxes


class TaxLine(ModelSQL, ModelView):
    'Tax Line'
    __name__ = 'account.tax.line'
    _rec_name = 'amount'
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    amount = fields.Numeric('Amount', digits=(16, Eval('currency_digits', 2)),
        required=True, depends=['currency_digits'])
    code = fields.Many2One('account.tax.code', 'Code', select=True,
        required=True,
        domain=[
            ('company', '=', Eval('company', -1)),
            ],
        depends=['company'])
    tax = fields.Many2One('account.tax', 'Tax', select=True,
        ondelete='RESTRICT',
        domain=[
            ('company', '=', Eval('company', -1)),
            ],
        depends=['company'])
    move_line = fields.Many2One('account.move.line', 'Move Line',
            required=True, select=True, ondelete='CASCADE')
    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company')

    @fields.depends('move_line')
    def on_change_with_currency_digits(self, name=None):
        if self.move_line:
            return self.move_line.currency_digits
        return 2

    @fields.depends('tax')
    def on_change_tax(self):
        self.code = None

    @fields.depends('_parent_move_line.account', 'move_line')
    def on_change_with_company(self, name=None):
        if self.move_line:
            return self.move_line.account.company.id


class TaxRuleTemplate(ModelSQL, ModelView):
    'Tax Rule Template'
    __name__ = 'account.tax.rule.template'
    name = fields.Char('Name', required=True)
    kind = fields.Selection(KINDS, 'Kind', required=True)
    lines = fields.One2Many('account.tax.rule.line.template', 'rule', 'Lines')
    account = fields.Many2One('account.account.template', 'Account Template',
            domain=[('parent', '=', None)], required=True)

    @staticmethod
    def default_kind():
        return 'both'

    def _get_tax_rule_value(self, rule=None):
        '''
        Set values for tax rule creation.
        '''
        res = {}
        if not rule or rule.name != self.name:
            res['name'] = self.name
        if not rule or rule.kind != self.kind:
            res['kind'] = self.kind
        if not rule or rule.template.id != self.id:
            res['template'] = self.id
        return res

    def create_rule(self, company_id, template2rule=None):
        '''
        Create tax rule based on template.
        template2rule is a dictionary with tax rule template id as key and tax
        rule id as value, used to convert template id into tax rule. The
        dictionary is filled with new tax rules.
        Return id of the tax rule created
        '''
        pool = Pool()
        Rule = pool.get('account.tax.rule')

        if template2rule is None:
            template2rule = {}

        if self.id not in template2rule:
            vals = self._get_tax_rule_value()
            vals['company'] = company_id
            new_rule, = Rule.create([vals])

            template2rule[self.id] = new_rule.id
        return template2rule[self.id]


class TaxRule(ModelSQL, ModelView):
    'Tax Rule'
    __name__ = 'account.tax.rule'
    name = fields.Char('Name', required=True)
    kind = fields.Selection(KINDS, 'Kind', required=True)
    company = fields.Many2One('company.company', 'Company', required=True,
        select=True, domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ])
    lines = fields.One2Many('account.tax.rule.line', 'rule', 'Lines')
    template = fields.Many2One('account.tax.rule.template', 'Template')

    @staticmethod
    def default_kind():
        return 'both'

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    def apply(self, tax, pattern):
        '''
        Apply rule on tax
        pattern is a dictonary with rule line field as key and match value as
        value.
        Return a list of the tax id to use or None
        '''
        pattern = pattern.copy()
        pattern['group'] = tax.group.id if tax and tax.group else None
        pattern['origin_tax'] = tax.id if tax else None

        for line in self.lines:
            if line.match(pattern):
                return line.get_taxes()
        return tax and [tax.id] or None

    def update_rule(self, template2rule=None):
        '''
        Update tax rule based on template.
        template2rule is a dictionary with tax rule template id as key and tax
        rule id as value, used to convert template id into tax rule. The
        dictionary is filled with new tax rules.
        '''

        if template2rule is None:
            template2rule = {}

        if self.template:
            vals = self.template._get_tax_rule_value(rule=self)
            if vals:
                self.write([self], vals)

            template2rule[self.template.id] = self.id


class TaxRuleLineTemplate(ModelSQL, ModelView):
    'Tax Rule Line Template'
    __name__ = 'account.tax.rule.line.template'
    rule = fields.Many2One('account.tax.rule.template', 'Rule', required=True,
            ondelete='CASCADE')
    group = fields.Many2One('account.tax.group', 'Tax Group',
        ondelete='RESTRICT')
    origin_tax = fields.Many2One('account.tax.template', 'Original Tax',
        domain=[
            ('account', '=', Eval('_parent_rule', {}).get('account', 0)),
            ('group', '=', Eval('group')),
            ['OR',
                ('group', '=', None),
                If(Eval('_parent_rule', {}).get('kind', 'both') == 'sale',
                    ('group.kind', 'in', ['sale', 'both']),
                    If(Eval('_parent_rule', {}).get('kind', 'both') ==
                        'purchase',
                        ('group.kind', 'in', ['purchase', 'both']),
                        ('group.kind', 'in', ['sale', 'purchase', 'both']))),
                ],
            ],
        help=('If the original tax template is filled, the rule will be '
            'applied only for this tax template.'),
        depends=['group'],
        ondelete='RESTRICT')
    tax = fields.Many2One('account.tax.template', 'Substitution Tax',
        domain=[
            ('account', '=', Eval('_parent_rule', {}).get('account', 0)),
            ('group', '=', Eval('group')),
            ['OR',
                ('group', '=', None),
                If(Eval('_parent_rule', {}).get('kind', 'both') == 'sale',
                    ('group.kind', 'in', ['sale', 'both']),
                    If(Eval('_parent_rule', {}).get('kind', 'both') ==
                        'purchase',
                        ('group.kind', 'in', ['purchase', 'both']),
                        ('group.kind', 'in', ['sale', 'purchase', 'both']))),
                ],
            ],
        depends=['group'],
        ondelete='RESTRICT')
    sequence = fields.Integer('Sequence')

    @classmethod
    def __setup__(cls):
        super(TaxRuleLineTemplate, cls).__setup__()
        cls._order.insert(0, ('rule', 'ASC'))
        cls._order.insert(0, ('sequence', 'ASC'))

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().cursor
        table = TableHandler(cursor, cls, module_name)

        super(TaxRuleLineTemplate, cls).__register__(module_name)

        # Migration from 2.4: drop required on sequence
        table.not_null_action('sequence', action='remove')

    @staticmethod
    def order_sequence(tables):
        table, _ = tables[None]
        return [Case((table.sequence == Null, 0), else_=1), table.sequence]

    def _get_tax_rule_line_value(self, rule_line=None):
        '''
        Set values for tax rule line creation.
        '''
        res = {}
        if not rule_line or rule_line.group != self.group:
            res['group'] = self.group.id if self.group else None
        if not rule_line or rule_line.sequence != self.sequence:
            res['sequence'] = self.sequence
        if not rule_line or rule_line.template != self:
            res['template'] = self.id
        return res

    def create_rule_line(self, template2tax, template2rule,
            template2rule_line=None):
        '''
        Create tax rule line based on template.
        template2tax is a dictionary with tax template id as key and tax id as
        value, used to convert template id into tax.
        template2rule is a dictionary with tax rule template id as key and tax
        rule id as value, used to convert template id into tax rule.
        template2rule_line is a dictionary with tax rule line template id as
        key and tax rule line id as value, used to convert template id into tax
        rule line. The dictionary is filled with new tax rule lines.
        Return id of the tax rule line created
        '''
        RuleLine = Pool().get('account.tax.rule.line')

        if template2rule_line is None:
            template2rule_line = {}

        if self.id not in template2rule_line:
            vals = self._get_tax_rule_line_value()
            vals['rule'] = template2rule[self.rule.id]
            if self.origin_tax:
                vals['origin_tax'] = template2tax[self.origin_tax.id]
            else:
                vals['origin_tax'] = None
            if self.tax:
                vals['tax'] = template2tax[self.tax.id]
            else:
                vals['tax'] = None
            new_rule_line, = RuleLine.create([vals])
            template2rule_line[self.id] = new_rule_line.id
        return template2rule_line[self.id]


class TaxRuleLine(ModelSQL, ModelView, MatchMixin):
    'Tax Rule Line'
    __name__ = 'account.tax.rule.line'
    _rec_name = 'tax'
    rule = fields.Many2One('account.tax.rule', 'Rule', required=True,
            select=True, ondelete='CASCADE')
    group = fields.Many2One('account.tax.group', 'Tax Group',
        ondelete='RESTRICT')
    origin_tax = fields.Many2One('account.tax', 'Original Tax',
        domain=[
            ('company', '=', Eval('_parent_rule', {}).get('company')),
            ('group', '=', Eval('group')),
            ['OR',
                ('group', '=', None),
                If(Eval('_parent_rule', {}).get('kind', 'both') == 'sale',
                    ('group.kind', 'in', ['sale', 'both']),
                    If(Eval('_parent_rule', {}).get('kind', 'both') ==
                        'purchase',
                        ('group.kind', 'in', ['purchase', 'both']),
                        ('group.kind', 'in', ['sale', 'purchase', 'both']))),
                ],
            ],
        help=('If the original tax is filled, the rule will be applied '
            'only for this tax.'),
        depends=['group'],
        ondelete='RESTRICT')
    tax = fields.Many2One('account.tax', 'Substitution Tax',
        domain=[
            ('company', '=', Eval('_parent_rule', {}).get('company')),
            ('group', '=', Eval('group')),
            ['OR',
                ('group', '=', None),
                If(Eval('_parent_rule', {}).get('kind', 'both') == 'sale',
                    ('group.kind', 'in', ['sale', 'both']),
                    If(Eval('_parent_rule', {}).get('kind', 'both') ==
                        'purchase',
                        ('group.kind', 'in', ['purchase', 'both']),
                        ('group.kind', 'in', ['sale', 'purchase', 'both']))),
                ],
            ],
        depends=['group'],
        ondelete='RESTRICT')
    sequence = fields.Integer('Sequence')
    template = fields.Many2One('account.tax.rule.line.template', 'Template')

    @classmethod
    def __setup__(cls):
        super(TaxRuleLine, cls).__setup__()
        cls._order.insert(0, ('rule', 'ASC'))
        cls._order.insert(0, ('sequence', 'ASC'))

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().cursor
        table = TableHandler(cursor, cls, module_name)

        super(TaxRuleLine, cls).__register__(module_name)

        # Migration from 2.4: drop required on sequence
        table.not_null_action('sequence', action='remove')

    @staticmethod
    def order_sequence(tables):
        table, _ = tables[None]
        return [Case((table.sequence == Null, 0), else_=1), table.sequence]

    def match(self, pattern):
        if 'group' in pattern and not self.group:
            if pattern['group']:
                return False
        return super(TaxRuleLine, self).match(pattern)

    def get_taxes(self):
        '''
        Return list of taxes for a line
        '''
        if self.tax:
            return [self.tax.id]
        return None

    def update_rule_line(self, template2tax, template2rule,
            template2rule_line=None):
        '''
        Update tax rule line based on template.
        template2tax is a dictionary with tax template id as key and tax id as
        value, used to convert template id into tax.
        template2rule is a dictionary with tax rule template id as key and tax
        rule id as value, used to convert template id into tax rule.
        template2rule_line is a dictionary with tax rule line template id as
        key and tax rule line id as value, used to convert template id into tax
        rule line. The dictionary is filled with new tax rule lines.
        '''
        if template2rule_line is None:
            template2rule_line = {}

        if self.template:
            vals = self.template._get_tax_rule_line_value(rule_line=self)
            if self.rule.id != template2rule[self.template.rule.id]:
                vals['rule'] = template2rule[self.template.rule.id]
            if self.origin_tax:
                if self.template.origin_tax:
                    if (self.origin_tax.id !=
                            template2tax[self.template.origin_tax.id]):
                        vals['origin_tax'] = template2tax[
                            self.template.origin_tax.id]
                else:
                    vals['origin_tax'] = None
            elif self.template.origin_tax:
                vals['origin_tax'] = template2tax[self.template.origin_tax.id]
            if self.tax:
                if self.template.tax:
                    if self.tax.id != template2tax[self.template.tax.id]:
                        vals['tax'] = template2tax[self.template.tax.id]
                else:
                    vals['tax'] = None
            elif self.template.tax:
                vals['tax'] = template2tax[self.template.tax.id]
            if vals:
                self.write([self], vals)
            template2rule_line[self.template.id] = self.id


class OpenTaxCode(Wizard):
    'Open Code'
    __name__ = 'account.tax.open_code'
    start_state = 'open_'
    open_ = StateAction('account.act_tax_line_form')

    def do_open_(self, action):
        pool = Pool()
        FiscalYear = pool.get('account.fiscalyear')
        Period = pool.get('account.period')

        if not Transaction().context.get('fiscalyear'):
            fiscalyears = FiscalYear.search([
                    ('state', '=', 'open'),
                    ])
        else:
            fiscalyears = [FiscalYear(Transaction().context['fiscalyear'])]

        periods = []
        if not Transaction().context.get('periods'):
            periods = Period.search([
                    ('fiscalyear', 'in', [f.id for f in fiscalyears]),
                    ])
        else:
            periods = Period.browse(Transaction().context['periods'])

        action['pyson_domain'] = PYSONEncoder().encode([
                ('move_line.period', 'in', [p.id for p in periods]),
                ('code', '=', Transaction().context['active_id']),
                ])
        if Transaction().context.get('fiscalyear'):
            action['pyson_context'] = PYSONEncoder().encode({
                    'fiscalyear': Transaction().context['fiscalyear'],
                    })
        else:
            action['pyson_context'] = PYSONEncoder().encode({
                    'periods': [p.id for p in periods],
                    })
        return action, {}


class AccountTemplateTaxTemplate(ModelSQL):
    'Account Template - Tax Template'
    __name__ = 'account.account.template-account.tax.template'
    _table = 'account_account_template_tax_rel'
    account = fields.Many2One('account.account.template', 'Account Template',
            ondelete='CASCADE', select=True, required=True)
    tax = fields.Many2One('account.tax.template', 'Tax Template',
            ondelete='RESTRICT', select=True, required=True)


class AccountTemplate2:
    __name__ = 'account.account.template'
    taxes = fields.Many2Many('account.account.template-account.tax.template',
            'account', 'tax', 'Default Taxes',
            domain=[('parent', '=', None)])


class AccountTax(ModelSQL):
    'Account - Tax'
    __name__ = 'account.account-account.tax'
    _table = 'account_account_tax_rel'
    account = fields.Many2One('account.account', 'Account', ondelete='CASCADE',
            select=True, required=True)
    tax = fields.Many2One('account.tax', 'Tax', ondelete='RESTRICT',
            select=True, required=True)


class Account2:
    __name__ = 'account.account'
    taxes = fields.Many2Many('account.account-account.tax',
            'account', 'tax', 'Default Taxes',
            domain=[
                ('company', '=', Eval('company')),
                ('parent', '=', None),
            ],
            help=('Default tax for manual encoding of move lines \n'
                'for journal types: "expense" and "revenue"'),
            depends=['company'])
