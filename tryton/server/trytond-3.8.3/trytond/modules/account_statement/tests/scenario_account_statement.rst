==========================
Account Statement Scenario
==========================

Imports::

    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from proteus import config, Model, Wizard, Report
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts
    >>> from.trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences, create_payment_term
    >>> today = datetime.date.today()

Create database::

    >>> config = config.set_trytond()
    >>> config.pool.test = True

Install account_statement and account_invoice::

    >>> Module = Model.get('ir.module')
    >>> modules = Module.find([
    ...     ('name', 'in', ('account_statement', 'account_invoice')),
    ... ])
    >>> for module in modules:
    ...     module.click('install')
    >>> Wizard('ir.module.install_upgrade').execute('upgrade')

Create company::

    >>> _ = create_company()
    >>> company = get_company()

Reload the context::

    >>> User = Model.get('res.user')
    >>> config._context = User.get_preferences(True, config.context)

Create fiscal year::

    >>> fiscalyear = set_fiscalyear_invoice_sequences(
    ...     create_fiscalyear(company))
    >>> fiscalyear.click('create_period')

Create chart of accounts::

    >>> _ = create_chart(company)
    >>> accounts = get_accounts(company)
    >>> receivable = accounts['receivable']
    >>> payable = accounts['payable']
    >>> revenue = accounts['revenue']
    >>> expense = accounts['expense']
    >>> cash = accounts['cash']

Create parties::

    >>> Party = Model.get('party.party')
    >>> supplier = Party(name='Supplier')
    >>> supplier.save()
    >>> customer = Party(name='Customer')
    >>> customer.save()

Create payment term::

    >>> payment_term = create_payment_term()
    >>> payment_term.save()

Create 2 customer invoices::

    >>> Invoice = Model.get('account.invoice')
    >>> customer_invoice1 = Invoice(type='out_invoice')
    >>> customer_invoice1.party = customer
    >>> customer_invoice1.payment_term = payment_term
    >>> invoice_line = customer_invoice1.lines.new()
    >>> invoice_line.quantity = 1
    >>> invoice_line.unit_price = Decimal('100')
    >>> invoice_line.account = revenue
    >>> invoice_line.description = 'Test'
    >>> customer_invoice1.click('post')
    >>> customer_invoice1.state
    u'posted'

    >>> customer_invoice2 = Invoice(type='out_invoice')
    >>> customer_invoice2.party = customer
    >>> customer_invoice2.payment_term = payment_term
    >>> invoice_line = customer_invoice2.lines.new()
    >>> invoice_line.quantity = 1
    >>> invoice_line.unit_price = Decimal('150')
    >>> invoice_line.account = revenue
    >>> invoice_line.description = 'Test'
    >>> customer_invoice2.click('post')
    >>> customer_invoice2.state
    u'posted'

Create 1 customer credit note::

    >>> customer_credit_note = Invoice(type='out_credit_note')
    >>> customer_credit_note.party = customer
    >>> customer_credit_note.payment_term = payment_term
    >>> invoice_line = customer_credit_note.lines.new()
    >>> invoice_line.quantity = 1
    >>> invoice_line.unit_price = Decimal('50')
    >>> invoice_line.account = revenue
    >>> invoice_line.description = 'Test'
    >>> customer_credit_note.click('post')
    >>> customer_credit_note.state
    u'posted'

Create 1 supplier invoices::

    >>> supplier_invoice = Invoice(type='in_invoice')
    >>> supplier_invoice.party = supplier
    >>> supplier_invoice.payment_term = payment_term
    >>> invoice_line = supplier_invoice.lines.new()
    >>> invoice_line.quantity = 1
    >>> invoice_line.unit_price = Decimal('50')
    >>> invoice_line.account = expense
    >>> invoice_line.description = 'Test'
    >>> supplier_invoice.invoice_date = today
    >>> supplier_invoice.click('post')
    >>> supplier_invoice.state
    u'posted'

Create statement::

    >>> StatementJournal = Model.get('account.statement.journal')
    >>> Statement = Model.get('account.statement')
    >>> StatementLine = Model.get('account.statement.line')
    >>> Sequence = Model.get('ir.sequence')
    >>> AccountJournal = Model.get('account.journal')

    >>> sequence = Sequence(name='Satement',
    ...     code='account.journal',
    ...     company=company,
    ... )
    >>> sequence.save()
    >>> account_journal = AccountJournal(name='Statement',
    ...     type='statement',
    ...     credit_account=cash,
    ...     debit_account=cash,
    ...     sequence=sequence,
    ... )
    >>> account_journal.save()

    >>> statement_journal = StatementJournal(name='Test',
    ...     journal=account_journal,
    ...     validation='balance',
    ... )
    >>> statement_journal.save()

    >>> statement = Statement(name='test',
    ...     journal=statement_journal,
    ...     start_balance=Decimal('0'),
    ...     end_balance=Decimal('80'),
    ... )

Received 180 from customer::

    >>> statement_line = StatementLine()
    >>> statement.lines.append(statement_line)
    >>> statement_line.date = today
    >>> statement_line.amount = Decimal('180')
    >>> statement_line.party = customer
    >>> statement_line.account == receivable
    True
    >>> statement_line.invoice = customer_invoice1
    >>> statement_line.amount
    Decimal('100.00')
    >>> statement_line = statement.lines[-1]
    >>> statement_line.amount
    Decimal('80.00')
    >>> statement_line.party == customer
    True
    >>> statement_line.account == receivable
    True
    >>> statement_line.invoice = customer_invoice2
    >>> statement_line.amount
    Decimal('80.00')

Paid 50 to customer::

    >>> statement_line = StatementLine()
    >>> statement.lines.append(statement_line)
    >>> statement_line.date = today
    >>> statement_line.amount = Decimal('-50')
    >>> statement_line.party = customer
    >>> statement_line.account = receivable
    >>> statement_line.invoice = customer_credit_note

Paid 50 to supplier::

    >>> statement_line = StatementLine()
    >>> statement.lines.append(statement_line)
    >>> statement_line.date = today
    >>> statement_line.amount = Decimal('-60')
    >>> statement_line.party = supplier
    >>> statement_line.account == payable
    True
    >>> statement_line.invoice = supplier_invoice
    >>> statement_line.amount
    Decimal('-50.00')
    >>> statement_line = statement.lines.pop()
    >>> statement_line.amount
    Decimal('-10.00')

    >>> statement.save()

Validate statement::

    >>> statement.click('validate_statement')
    >>> statement.state
    u'validated'

Test invoice state::

    >>> customer_invoice1.reload()
    >>> customer_invoice1.state
    u'paid'
    >>> customer_invoice2.reload()
    >>> customer_invoice2.state
    u'posted'
    >>> customer_invoice2.amount_to_pay
    Decimal('70.00')
    >>> customer_credit_note.reload()
    >>> customer_credit_note.state
    u'paid'
    >>> supplier_invoice.reload()
    >>> supplier_invoice.state
    u'paid'

Test statement report::

    >>> report = Report('account.statement')
    >>> _ = report.execute([statement], {})

Let's test the negative amount version of the supplier/customer invoices::

    >>> customer_invoice3 = Invoice(type='out_invoice')
    >>> customer_invoice3.party = customer
    >>> customer_invoice3.payment_term = payment_term
    >>> invoice_line = customer_invoice3.lines.new()
    >>> invoice_line.quantity = 1
    >>> invoice_line.unit_price = Decimal('-120')
    >>> invoice_line.account = revenue
    >>> invoice_line.description = 'Test'
    >>> customer_invoice3.click('post')
    >>> customer_invoice3.state
    u'posted'

    >>> supplier_invoice2 = Invoice(type='in_invoice')
    >>> supplier_invoice2.party = supplier
    >>> supplier_invoice2.payment_term = payment_term
    >>> invoice_line = supplier_invoice2.lines.new()
    >>> invoice_line.quantity = 1
    >>> invoice_line.unit_price = Decimal('-40')
    >>> invoice_line.account = expense
    >>> invoice_line.description = 'Test'
    >>> supplier_invoice2.invoice_date = today
    >>> supplier_invoice2.click('post')
    >>> supplier_invoice2.state
    u'posted'

    >>> statement = Statement(name='test negative',
    ...     journal=statement_journal,
    ...     end_balance=Decimal('0'),
    ... )

    >>> statement_line = StatementLine()
    >>> statement.lines.append(statement_line)
    >>> statement_line.date = today
    >>> statement_line.party = customer
    >>> statement_line.account = receivable
    >>> statement_line.amount = Decimal(-120)
    >>> statement_line.invoice = customer_invoice3
    >>> statement_line.invoice.id == customer_invoice3.id
    True

    >>> statement_line = StatementLine()
    >>> statement.lines.append(statement_line)
    >>> statement_line.date = today
    >>> statement_line.party = supplier
    >>> statement_line.account = payable
    >>> statement_line.amount = Decimal(50)
    >>> statement_line.invoice = supplier_invoice2
    >>> statement_line.amount
    Decimal('40.00')
    >>> len(statement.lines)
    3
    >>> statement.lines[-1].amount
    Decimal('10.00')

Testing the use of an invoice in multiple statements::

    >>> customer_invoice4 = Invoice(type='out_invoice')
    >>> customer_invoice4.party = customer
    >>> customer_invoice4.payment_term = payment_term
    >>> invoice_line = customer_invoice4.lines.new()
    >>> invoice_line.quantity = 1
    >>> invoice_line.unit_price = Decimal('300')
    >>> invoice_line.account = revenue
    >>> invoice_line.description = 'Test'
    >>> customer_invoice4.click('post')
    >>> customer_invoice4.state
    u'posted'

    >>> statement1 = Statement(name='1', journal=statement_journal)
    >>> statement1.end_balance = Decimal(380)
    >>> statement_line = statement1.lines.new()
    >>> statement_line.date = today
    >>> statement_line.party = customer
    >>> statement_line.account = receivable
    >>> statement_line.amount = Decimal(300)
    >>> statement_line.invoice = customer_invoice4
    >>> statement1.save()

    >>> statement2 = Statement(name='2', journal=statement_journal)
    >>> statement2.end_balance = Decimal(680)
    >>> statement_line = statement2.lines.new()
    >>> statement_line.date = today
    >>> statement_line.party = customer
    >>> statement_line.account = receivable
    >>> statement_line.amount = Decimal(300)
    >>> statement_line.invoice = customer_invoice4
    >>> statement2.save()

    >>> statement1.click('validate_statement') # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
        ...
    UserWarning: ...
    >>> statement2.reload()
    >>> Model.get('res.user.warning')(user=config.user,
    ...     name=str(statement2.lines[0].id), always=True).save()
    >>> statement1.click('validate_statement')
    >>> statement1.state
    u'validated'

    >>> statement1.reload()
    >>> bool(statement1.lines[0].invoice)
    True
    >>> statement2.reload()
    >>> bool(statement2.lines[0].invoice)
    False

Testing balance validation::

    >>> journal_balance = StatementJournal(name='Balance',
    ...     journal=account_journal,
    ...     validation='balance',
    ...     )
    >>> journal_balance.save()

    >>> statement = Statement(name='balance')
    >>> statement.journal = journal_balance
    >>> statement.start_balance = Decimal('50.00')
    >>> statement.end_balance = Decimal('150.00')
    >>> line = statement.lines.new()
    >>> line.date = today
    >>> line.amount = Decimal('60.00')
    >>> line.account = receivable
    >>> line.party = customer
    >>> statement.click('validate_statement')  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
        ...
    UserError: ...

    >>> second_line = statement.lines.new()
    >>> second_line.date = today
    >>> second_line.amount = Decimal('40.00')
    >>> second_line.account = receivable
    >>> second_line.party = customer
    >>> statement.click('validate_statement')

Testing amount validation::

    >>> journal_amount = StatementJournal(name='Amount',
    ...     journal=account_journal,
    ...     validation='amount',
    ...     )
    >>> journal_amount.save()

    >>> statement = Statement(name='amount')
    >>> statement.journal = journal_amount
    >>> statement.total_amount = Decimal('80.00')
    >>> line = statement.lines.new()
    >>> line.date = today
    >>> line.amount = Decimal('50.00')
    >>> line.account = receivable
    >>> line.party = customer
    >>> statement.click('validate_statement')  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
        ...
    UserError: ...

    >>> second_line = statement.lines.new()
    >>> second_line.date = today
    >>> second_line.amount = Decimal('30.00')
    >>> second_line.account = receivable
    >>> second_line.party = customer
    >>> statement.click('validate_statement')

Test number of lines validation::

    >>> journal_number = StatementJournal(name='Number',
    ...     journal=account_journal,
    ...     validation='number_of_lines',
    ...     )
    >>> journal_number.save()

    >>> statement = Statement(name='number')
    >>> statement.journal = journal_number
    >>> statement.number_of_lines = 2
    >>> line = statement.lines.new()
    >>> line.date = today
    >>> line.amount = Decimal('50.00')
    >>> line.account = receivable
    >>> line.party = customer
    >>> statement.click('validate_statement')  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
        ...
    UserError: ...

    >>> second_line = statement.lines.new()
    >>> second_line.date = today
    >>> second_line.amount = Decimal('10.00')
    >>> second_line.account = receivable
    >>> second_line.party = customer
    >>> statement.click('validate_statement')
