# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from decimal import Decimal
from dateutil.relativedelta import relativedelta

from sql import Null, Column
from sql.conditionals import Case

from trytond.model import ModelView, ModelSQL, fields
from trytond import backend
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.pool import Pool
from trytond.wizard import Wizard, StateView, Button

__all__ = ['PaymentTerm', 'PaymentTermLine', 'PaymentTermLineRelativeDelta',
    'TestPaymentTerm', 'TestPaymentTermView', 'TestPaymentTermViewResult']


class PaymentTerm(ModelSQL, ModelView):
    'Payment Term'
    __name__ = 'account.invoice.payment_term'
    name = fields.Char('Name', size=None, required=True, translate=True)
    active = fields.Boolean('Active')
    description = fields.Text('Description', translate=True)
    lines = fields.One2Many('account.invoice.payment_term.line', 'payment',
            'Lines')

    @classmethod
    def __setup__(cls):
        super(PaymentTerm, cls).__setup__()
        cls._order.insert(0, ('name', 'ASC'))
        cls._error_messages.update({
                'invalid_line': ('Invalid line "%(line)s" in payment term '
                    '"%(term)s".'),
                'missing_remainder': ('Missing remainder line in payment term '
                    '"%s".'),
                'last_remainder': ('Last line of payment term "%s" must be of '
                    'type remainder.'),
                })

    @classmethod
    def validate(cls, terms):
        super(PaymentTerm, cls).validate(terms)
        for term in terms:
            term.check_remainder()

    def check_remainder(self):
        if not self.lines or not self.lines[-1].type == 'remainder':
            self.raise_user_error('last_remainder', self.rec_name)

    @staticmethod
    def default_active():
        return True

    def compute(self, amount, currency, date=None):
        """Calculate payment terms and return a list of tuples
        with (date, amount) for each payment term line.

        amount must be a Decimal used for the calculation.
        If specified, date will be used as the start date, otherwise current
        date will be used.
        """
        # TODO implement business_days
        # http://pypi.python.org/pypi/BusinessHours/
        Date = Pool().get('ir.date')

        sign = 1 if amount >= Decimal('0.0') else -1
        res = []
        if date is None:
            date = Date.today()
        remainder = amount
        for line in self.lines:
            value = line.get_value(remainder, amount, currency)
            value_date = line.get_date(date)
            if not value or not value_date:
                if (not remainder) and line.amount:
                    self.raise_user_error('invalid_line', {
                            'line': line.rec_name,
                            'term': self.rec_name,
                            })
                else:
                    continue
            if ((remainder - value) * sign) < Decimal('0.0'):
                res.append((value_date, remainder))
                break
            res.append((value_date, value))
            remainder -= value

        if not currency.is_zero(remainder):
            self.raise_user_error('missing_remainder', (self.rec_name,))
        return res


class PaymentTermLine(ModelSQL, ModelView):
    'Payment Term Line'
    __name__ = 'account.invoice.payment_term.line'
    sequence = fields.Integer('Sequence',
        help='Use to order lines in ascending order')
    payment = fields.Many2One('account.invoice.payment_term', 'Payment Term',
            required=True, ondelete="CASCADE")
    type = fields.Selection([
            ('fixed', 'Fixed'),
            ('percent', 'Percentage on Remainder'),
            ('percent_on_total', 'Percentage on Total'),
            ('remainder', 'Remainder'),
            ], 'Type', required=True)
    percentage = fields.Numeric('Percentage', digits=(16, 8),
        states={
            'invisible': ~Eval('type').in_(['percent', 'percent_on_total']),
            'required': Eval('type').in_(['percent', 'percent_on_total']),
            }, depends=['type'])
    divisor = fields.Numeric('Divisor', digits=(16, 8),
        states={
            'invisible': ~Eval('type').in_(['percent', 'percent_on_total']),
            'required': Eval('type').in_(['percent', 'percent_on_total']),
            }, depends=['type'])
    amount = fields.Numeric('Amount', digits=(16, Eval('currency_digits', 2)),
        states={
            'invisible': Eval('type') != 'fixed',
            'required': Eval('type') == 'fixed',
            }, depends=['type', 'currency_digits'])
    currency = fields.Many2One('currency.currency', 'Currency',
        states={
            'invisible': Eval('type') != 'fixed',
            'required': Eval('type') == 'fixed',
            }, depends=['type'])
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    relativedeltas = fields.One2Many(
        'account.invoice.payment_term.line.relativedelta', 'line', 'Deltas')

    @classmethod
    def __setup__(cls):
        super(PaymentTermLine, cls).__setup__()
        cls._order.insert(0, ('sequence', 'ASC'))
        cls._error_messages.update({
                'invalid_percentage_and_divisor': ('Percentage and '
                    'Divisor values are not consistent in line "%(line)s" '
                    'of payment term "%(term)s".'),
                })

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        sql_table = cls.__table__()
        super(PaymentTermLine, cls).__register__(module_name)
        cursor = Transaction().cursor
        table = TableHandler(cursor, cls, module_name)

        # Migration from 1.0 percent change into percentage
        if table.column_exist('percent'):
            cursor.execute(*sql_table.update(
                    columns=[sql_table.percentage],
                    values=[sql_table.percent * 100]))
            table.drop_column('percent', exception=True)

        # Migration from 2.2
        if table.column_exist('delay'):
            cursor.execute(*sql_table.update(
                    columns=[sql_table.day],
                    values=[31],
                    where=sql_table.delay == 'end_month'))
            table.drop_column('delay', exception=True)
            lines = cls.search([])
            for line in lines:
                if line.percentage:
                    cls.write([line], {
                            'divisor': cls.round(Decimal('100.0') /
                                line.percentage, cls.divisor.digits[1]),
                            })

        # Migration from 2.4: drop required on sequence
        table.not_null_action('sequence', action='remove')

    @staticmethod
    def order_sequence(tables):
        table, _ = tables[None]
        return [Case((table.sequence == Null, 0), else_=1), table.sequence]

    @staticmethod
    def default_currency_digits():
        return 2

    @staticmethod
    def default_type():
        return 'remainder'

    @fields.depends('type')
    def on_change_type(self):
        if self.type != 'fixed':
            self.amount = Decimal('0.0')
            self.currency = None
        if self.type not in ('percent', 'percent_on_total'):
            self.percentage = Decimal('0.0')
            self.divisor = Decimal('0.0')

    @fields.depends('percentage')
    def on_change_percentage(self):
        if not self.percentage:
            self.divisor = 0.0
        else:
            self.divisor = self.round(Decimal('100.0') / self.percentage,
                self.__class__.divisor.digits[1])

    @fields.depends('divisor')
    def on_change_divisor(self):
        if not self.divisor:
            self.percentage = 0.0
        else:
            self.percentage = self.round(Decimal('100.0') / self.divisor,
                self.__class__.percentage.digits[1])

    @fields.depends('currency')
    def on_change_with_currency_digits(self, name=None):
        if self.currency:
            return self.currency.digits
        return 2

    def get_delta(self):
        return {
            'day': self.day,
            'month': int(self.month) if self.month else None,
            'days': self.days,
            'weeks': self.weeks,
            'months': self.months,
            'weekday': int(self.weekday) if self.weekday else None,
            }

    def get_date(self, date):
        for relativedelta_ in self.relativedeltas:
            date += relativedelta_.get()
        return date

    def get_value(self, remainder, amount, currency):
        Currency = Pool().get('currency.currency')
        if self.type == 'fixed':
            return Currency.compute(self.currency, self.amount, currency)
        elif self.type == 'percent':
            return currency.round(
                remainder * self.percentage / Decimal('100'))
        elif self.type == 'percent_on_total':
            return currency.round(
                amount * self.percentage / Decimal('100'))
        elif self.type == 'remainder':
            return currency.round(remainder)
        return None

    @staticmethod
    def round(number, digits):
        quantize = Decimal(10) ** -Decimal(digits)
        return Decimal(number).quantize(quantize)

    @classmethod
    def validate(cls, lines):
        super(PaymentTermLine, cls).validate(lines)
        cls.check_percentage_and_divisor(lines)

    @classmethod
    def check_percentage_and_divisor(cls, lines):
        "Check consistency between percentage and divisor"
        percentage_digits = cls.percentage.digits[1]
        divisor_digits = cls.divisor.digits[1]
        for line in lines:
            if line.type not in ('percent', 'percent_on_total'):
                continue
            if line.percentage is None or line.divisor is None:
                cls.raise_user_error('invalid_percentage_and_divisor', {
                        'line': line.rec_name,
                        'term': line.payment.rec_name,
                        })
            if line.percentage == line.divisor == Decimal('0.0'):
                continue
            percentage = line.percentage
            divisor = line.divisor
            calc_percentage = cls.round(Decimal('100.0') / divisor,
                    percentage_digits)
            calc_divisor = cls.round(Decimal('100.0') / percentage,
                    divisor_digits)
            if (percentage == Decimal('0.0') or divisor == Decimal('0.0')
                    or percentage != calc_percentage
                    and divisor != calc_divisor):
                cls.raise_user_error('invalid_percentage_and_divisor', {
                        'line': line.rec_name,
                        'term': line.payment.rec_name,
                        })


class PaymentTermLineRelativeDelta(ModelSQL, ModelView):
    'Payment Term Line Relative Delta'
    __name__ = 'account.invoice.payment_term.line.relativedelta'
    sequence = fields.Integer('Sequence')
    line = fields.Many2One('account.invoice.payment_term.line',
        'Payment Term Line', required=True, ondelete='CASCADE')
    day = fields.Integer('Day of Month',
        domain=['OR',
            ('day', '=', None),
            [('day', '>=', 1), ('day', '<=', 31)],
            ])
    month = fields.Selection([
            (None, ''),
            ('1', 'January'),
            ('2', 'February'),
            ('3', 'March'),
            ('4', 'April'),
            ('5', 'May'),
            ('6', 'June'),
            ('7', 'July'),
            ('8', 'August'),
            ('9', 'September'),
            ('10', 'October'),
            ('11', 'November'),
            ('12', 'December'),
            ], 'Month', sort=False)
    weekday = fields.Selection([
            (None, ''),
            ('0', 'Monday'),
            ('1', 'Tuesday'),
            ('2', 'Wednesday'),
            ('3', 'Thursday'),
            ('4', 'Friday'),
            ('5', 'Saturday'),
            ('6', 'Sunday'),
            ], 'Day of Week', sort=False)
    months = fields.Integer('Number of Months', required=True)
    weeks = fields.Integer('Number of Weeks', required=True)
    days = fields.Integer('Number of Days', required=True)

    @classmethod
    def __setup__(cls):
        super(PaymentTermLineRelativeDelta, cls).__setup__()
        cls._order.insert(0, ('sequence', 'ASC'))

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().cursor
        pool = Pool()
        Line = pool.get('account.invoice.payment_term.line')
        sql_table = cls.__table__()
        line = Line.__table__()

        super(PaymentTermLineRelativeDelta, cls).__register__(module_name)

        line_table = TableHandler(cursor, Line, module_name)

        # Migration from 3.4
        fields = ['day', 'month', 'weekday', 'months', 'weeks', 'days']
        if any(line_table.column_exist(f) for f in fields):
            columns = ([line.id.as_('line')]
                + [Column(line, f) for f in fields])
            cursor.execute(*sql_table.insert(
                    columns=[sql_table.line]
                    + [Column(sql_table, f) for f in fields],
                    values=line.select(*columns)))
            for field in fields:
                line_table.drop_column(field, exception=True)

    @staticmethod
    def order_sequence(tables):
        table, _ = tables[None]
        return [Case((table.sequence == Null, 0), else_=1), table.sequence]

    @staticmethod
    def default_months():
        return 0

    @staticmethod
    def default_weeks():
        return 0

    @staticmethod
    def default_days():
        return 0

    def get(self):
        "Return the relativedelta"
        return relativedelta(
            day=self.day,
            month=int(self.month) if self.month else None,
            days=self.days,
            weeks=self.weeks,
            months=self.months,
            weekday=int(self.weekday) if self.weekday else None,
            )


class TestPaymentTerm(Wizard):
    'Test Payment Term'
    __name__ = 'account.invoice.payment_term.test'
    start_state = 'test'
    test = StateView('account.invoice.payment_term.test',
        'account_invoice.payment_term_test_view_form',
        [Button('Close', 'end', 'tryton-close', default=True)])

    def default_test(self, fields):
        context = Transaction().context
        default = {}
        if context['active_model'] == 'account.invoice.payment_term':
            default['payment_term'] = context['active_id']
        return default


class TestPaymentTermView(ModelView):
    'Test Payment Term'
    __name__ = 'account.invoice.payment_term.test'
    payment_term = fields.Many2One('account.invoice.payment_term',
        'Payment Term', required=True)
    date = fields.Date('Date')
    amount = fields.Numeric('Amount', required=True,
        digits=(16, Eval('currency_digits', 2)), depends=['currency_digits'])
    currency = fields.Many2One('currency.currency', 'Currency', required=True)
    currency_digits = fields.Integer('Currency Digits')
    result = fields.One2Many('account.invoice.payment_term.test.result',
        None, 'Result', readonly=True)

    @staticmethod
    def default_currency():
        pool = Pool()
        Company = pool.get('company.company')
        company = Transaction().context.get('company')
        if company:
            return Company(company).currency.id

    @fields.depends('currency')
    def on_change_with_currency_digits(self):
        if self.currency:
            return self.currency.digits
        return 2

    @fields.depends('payment_term', 'date', 'amount', 'currency', 'result')
    def on_change_with_result(self):
        pool = Pool()
        Result = pool.get('account.invoice.payment_term.test.result')
        result = []
        if (self.payment_term and self.amount and self.currency):
            for date, amount in self.payment_term.compute(
                    self.amount, self.currency, self.date):
                result.append(Result(
                        date=date, amount=amount,
                        currency_digits=self.currency.digits))
        self.result = result
        return self._changed_values.get('result', [])


class TestPaymentTermViewResult(ModelView):
    'Test Payment Term'
    __name__ = 'account.invoice.payment_term.test.result'
    date = fields.Date('Date', readonly=True)
    amount = fields.Numeric('Amount', readonly=True,
        digits=(16, Eval('currency_digits', 2)), depends=['currency_digits'])
    currency_digits = fields.Integer('Currency Digits')
