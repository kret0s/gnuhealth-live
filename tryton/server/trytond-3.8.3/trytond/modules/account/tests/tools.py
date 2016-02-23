# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import datetime

from dateutil.relativedelta import relativedelta

from proteus import Model, Wizard

from trytond.modules.company.tests.tools import get_company

__all__ = ['create_fiscalyear', 'create_chart', 'get_accounts',
    'create_tax', 'set_tax_code']


def create_fiscalyear(company=None, today=None, config=None):
    "Create a fiscal year for the company on today"
    FiscalYear = Model.get('account.fiscalyear', config=config)
    Sequence = Model.get('ir.sequence', config=config)

    if not company:
        company = get_company()

    if not today:
        today = datetime.date.today()

    fiscalyear = FiscalYear(name=str(today.year))
    fiscalyear.start_date = today + relativedelta(month=1, day=1)
    fiscalyear.end_date = today + relativedelta(month=12, day=31)
    fiscalyear.company = company

    post_move_sequence = Sequence(name=str(today.year), code='account.move',
        company=company)
    post_move_sequence.save()
    fiscalyear.post_move_sequence = post_move_sequence
    return fiscalyear


def create_chart(company=None, config=None):
    "Create chart of accounts"
    AccountTemplate = Model.get('account.account.template', config=config)
    ModelData = Model.get('ir.model.data')

    if not company:
        company = get_company()
    data, = ModelData.find([
            ('module', '=', 'account'),
            ('fs_id', '=', 'account_template_root_en'),
            ], limit=1)

    account_template = AccountTemplate(data.db_id)

    create_chart = Wizard('account.create_chart')
    create_chart.execute('account')
    create_chart.form.account_template = account_template
    create_chart.form.company = company
    create_chart.execute('create_account')

    accounts = get_accounts(company, config=config)

    create_chart.form.account_receivable = accounts['receivable']
    create_chart.form.account_payable = accounts['payable']
    create_chart.execute('create_properties')
    return create_chart


def get_accounts(company=None, config=None):
    "Return accounts per kind"
    Account = Model.get('account.account', config=config)

    if not company:
        company = get_company()

    accounts = Account.find([
            ('kind', 'in', ['receivable', 'payable', 'revenue', 'expense']),
            ('company', '=', company.id),
            ])
    accounts = {a.kind: a for a in accounts}
    cash, = Account.find([
            ('kind', '=', 'other'),
            ('company', '=', company.id),
            ('name', '=', 'Main Cash'),
            ])
    accounts['cash'] = cash
    tax, = Account.find([
            ('kind', '=', 'other'),
            ('company', '=', company.id),
            ('name', '=', 'Main Tax'),
            ])
    accounts['tax'] = tax
    return accounts


def create_tax(rate, company=None, config=None):
    "Create a tax of rate"
    Tax = Model.get('account.tax', config=config)

    if not company:
        company = get_company()

    accounts = get_accounts(company)

    tax = Tax()
    tax.name = 'Tax %s' % rate
    tax.description = tax.name
    tax.type = 'percentage'
    tax.rate = rate
    tax.invoice_account = accounts['tax']
    tax.credit_note_account = accounts['tax']
    return tax


def set_tax_code(tax, config=None):
    "Set code on tax"
    TaxCode = Model.get('account.tax.code', config=config)
    invoice_base_code = TaxCode(name='Invoice Base')
    invoice_base_code.save()
    invoice_tax_code = TaxCode(name='Invoice Tax')
    invoice_tax_code.save()
    credit_note_base_code = TaxCode(name='Credit Note Base')
    credit_note_base_code.save()
    credit_note_tax_code = TaxCode(name='Credit Note Tax')
    credit_note_tax_code.save()

    tax.invoice_base_code = invoice_base_code
    tax.invoice_tax_code = invoice_tax_code
    tax.credit_note_base_code = credit_note_base_code
    tax.credit_note_tax_code = credit_note_tax_code

    return tax
