# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from decimal import Decimal

from sql import Literal, Null
from sql.aggregate import Sum
from sql.conditionals import Coalesce

from trytond.model import fields
from trytond.pyson import Eval, Bool
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta
from trytond.tools import reduce_ids, grouped_slice

__all__ = ['Party']
__metaclass__ = PoolMeta


class Party:
    __name__ = 'party.party'
    account_payable = fields.Property(fields.Many2One('account.account',
            'Account Payable', domain=[
                ('kind', '=', 'payable'),
                ('company', '=', Eval('context', {}).get('company', -1)),
                ],
            states={
                'required': Bool(Eval('context', {}).get('company')),
                'invisible': ~Eval('context', {}).get('company'),
                }))
    account_receivable = fields.Property(fields.Many2One('account.account',
            'Account Receivable', domain=[
                ('kind', '=', 'receivable'),
                ('company', '=', Eval('context', {}).get('company', -1)),
                ],
            states={
                'required': Bool(Eval('context', {}).get('company')),
                'invisible': ~Eval('context', {}).get('company'),
                }))
    customer_tax_rule = fields.Property(fields.Many2One('account.tax.rule',
            'Customer Tax Rule',
            domain=[
                ('company', '=', Eval('context', {}).get('company', -1)),
                ('kind', 'in', ['sale', 'both']),
                ],
            states={
                'invisible': ~Eval('context', {}).get('company'),
                }, help='Apply this rule on taxes when party is customer.'))
    supplier_tax_rule = fields.Property(fields.Many2One('account.tax.rule',
            'Supplier Tax Rule',
            domain=[
                ('company', '=', Eval('context', {}).get('company', -1)),
                ('kind', 'in', ['purchase', 'both']),
                ],
            states={
                'invisible': ~Eval('context', {}).get('company'),
                }, help='Apply this rule on taxes when party is supplier.'))
    receivable = fields.Function(fields.Numeric('Receivable'),
            'get_receivable_payable', searcher='search_receivable_payable')
    payable = fields.Function(fields.Numeric('Payable'),
            'get_receivable_payable', searcher='search_receivable_payable')
    receivable_today = fields.Function(fields.Numeric('Receivable Today'),
            'get_receivable_payable', searcher='search_receivable_payable')
    payable_today = fields.Function(fields.Numeric('Payable Today'),
            'get_receivable_payable', searcher='search_receivable_payable')

    @classmethod
    def get_receivable_payable(cls, parties, names):
        '''
        Function to compute receivable, payable (today or not) for party ids.
        '''
        result = {}
        pool = Pool()
        MoveLine = pool.get('account.move.line')
        Account = pool.get('account.account')
        User = pool.get('res.user')
        Date = pool.get('ir.date')
        cursor = Transaction().cursor

        line = MoveLine.__table__()
        account = Account.__table__()

        for name in names:
            if name not in ('receivable', 'payable',
                    'receivable_today', 'payable_today'):
                raise Exception('Bad argument')
            result[name] = dict((p.id, Decimal('0.0')) for p in parties)

        user = User(Transaction().user)
        if not user.company:
            return result
        company_id = user.company.id

        line_query, _ = MoveLine.query_get(line)

        amount = Sum(Coalesce(line.debit, 0) - Coalesce(line.credit, 0))
        for name in names:
            code = name
            today_where = Literal(True)
            if name in ('receivable_today', 'payable_today'):
                code = name[:-6]
                today_where = ((line.maturity_date <= Date.today())
                    | (line.maturity_date == Null))
            for sub_parties in grouped_slice(parties):
                sub_ids = [p.id for p in sub_parties]
                party_where = reduce_ids(line.party, sub_ids)
                cursor.execute(*line.join(account,
                        condition=account.id == line.account
                        ).select(line.party, amount,
                        where=(account.active
                            & (account.kind == code)
                            & (line.reconciliation == Null)
                            & (account.company == company_id)
                            & line_query
                            & party_where
                            & today_where
                            & (account.kind == code)),
                        group_by=line.party))
                for party, value in cursor.fetchall():
                    # SQLite uses float for SUM
                    if not isinstance(value, Decimal):
                        value = Decimal(str(value))
                    result[name][party] = value
        return result

    @classmethod
    def search_receivable_payable(cls, name, clause):
        pool = Pool()
        MoveLine = pool.get('account.move.line')
        Account = pool.get('account.account')
        User = pool.get('res.user')
        Date = pool.get('ir.date')

        line = MoveLine.__table__()
        account = Account.__table__()

        if name not in ('receivable', 'payable',
                'receivable_today', 'payable_today'):
            raise Exception('Bad argument')

        user = User(Transaction().user)
        if not user.company:
            return []
        company_id = user.company.id

        code = name
        today_query = Literal(True)
        if name in ('receivable_today', 'payable_today'):
            code = name[:-6]
            today_query = ((line.maturity_date <= Date.today())
                | (line.maturity_date == Null))

        line_query, _ = MoveLine.query_get(line)
        Operator = fields.SQL_OPERATORS[clause[1]]

        query = line.join(account, condition=account.id == line.account
                ).select(line.party,
                    where=account.active
                    & (account.kind == code)
                    & (line.party != Null)
                    & (line.reconciliation == Null)
                    & (account.company == company_id)
                    & line_query & today_query,
                    group_by=line.party,
                    having=Operator(Sum(Coalesce(line.debit, 0)
                            - Coalesce(line.credit, 0)),
                        Decimal(clause[2] or 0)))
        return [('id', 'in', query)]
