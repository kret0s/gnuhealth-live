==================================
Account Stock Continental Scenario
==================================

Imports::

    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from proteus import config, Model, Wizard
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts
    >>> from.trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences, create_payment_term
    >>> from trytond.modules.account_stock_continental.tests.tools import \
    ...     add_stock_accounts
    >>> today = datetime.date.today()

Create database::

    >>> config = config.set_trytond()
    >>> config.pool.test = True

Install account_stock_continental, sale and purchase::

    >>> Module = Model.get('ir.module')
    >>> modules = Module.find([
    ...         ('name', 'in', ('account_stock_continental',
    ...             'sale', 'purchase', 'sale_supply_drop_shipment')),
    ...     ])
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
    >>> fiscalyear.account_stock_method = 'continental'
    >>> fiscalyear.click('create_period')

Create chart of accounts::

    >>> _ = create_chart(company)
    >>> accounts = add_stock_accounts(get_accounts(company), company)
    >>> receivable = accounts['receivable']
    >>> payable = accounts['payable']
    >>> revenue = accounts['revenue']
    >>> expense = accounts['expense']
    >>> stock = accounts['stock']
    >>> stock_customer = accounts['stock_customer']
    >>> stock_lost_found = accounts['stock_lost_found']
    >>> stock_production = accounts['stock_production']
    >>> stock_supplier = accounts['stock_supplier']

Create parties::

    >>> Party = Model.get('party.party')
    >>> supplier = Party(name='Supplier')
    >>> supplier.save()
    >>> customer = Party(name='Customer')
    >>> customer.save()

Create category::

    >>> ProductCategory = Model.get('product.category')
    >>> category = ProductCategory(name='Category')
    >>> category.save()

Create product::

    >>> ProductUom = Model.get('product.uom')
    >>> unit, = ProductUom.find([('name', '=', 'Unit')])
    >>> ProductTemplate = Model.get('product.template')
    >>> Product = Model.get('product.product')
    >>> product = Product()
    >>> template = ProductTemplate()
    >>> template.name = 'product'
    >>> template.category = category
    >>> template.default_uom = unit
    >>> template.type = 'goods'
    >>> template.purchasable = True
    >>> template.salable = True
    >>> template.list_price = Decimal('10')
    >>> template.cost_price = Decimal('5')
    >>> template.cost_price_method = 'fixed'
    >>> template.delivery_time = 0
    >>> template.account_expense = expense
    >>> template.account_revenue = revenue
    >>> template.account_stock = stock
    >>> template.account_stock_supplier = stock_supplier
    >>> template.account_stock_customer = stock_customer
    >>> template.account_stock_production = stock_production
    >>> template.account_stock_lost_found = stock_lost_found
    >>> template.save()
    >>> product.template = template
    >>> product.save()
    >>> template_average, = ProductTemplate.duplicate([template], {
    ...         'cost_price_method': 'average',
    ...         })
    >>> product_average, = Product.duplicate([product], {
    ...         'template': template_average.id,
    ...         })

Create payment term::

    >>> payment_term = create_payment_term()
    >>> payment_term.save()

Purchase 12 products::

    >>> Purchase = Model.get('purchase.purchase')
    >>> purchase = Purchase()
    >>> purchase.party = supplier
    >>> purchase.payment_term = payment_term
    >>> purchase.invoice_method = 'shipment'
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.product = product
    >>> purchase_line.quantity = 5.0
    >>> purchase_line.unit_price = Decimal(4)
    >>> purchase_line = purchase.lines.new()
    >>> purchase_line.product = product_average
    >>> purchase_line.quantity = 7.0
    >>> purchase_line.unit_price = Decimal(6)
    >>> purchase.click('quote')
    >>> purchase.click('confirm')
    >>> purchase.click('process')
    >>> purchase.state
    u'processing'

Receive 9 products::

    >>> ShipmentIn = Model.get('stock.shipment.in')
    >>> Move = Model.get('stock.move')
    >>> shipment = ShipmentIn(supplier=supplier)
    >>> move, = [m for m in purchase.moves if m.product == product]
    >>> move = Move(move.id)
    >>> shipment.incoming_moves.append(move)
    >>> move.quantity = 4.0
    >>> move, = [m for m in purchase.moves if m.product == product_average]
    >>> move = Move(move.id)
    >>> shipment.incoming_moves.append(move)
    >>> move.quantity = 5.0
    >>> shipment.click('receive')
    >>> shipment.click('done')
    >>> shipment.state
    u'done'
    >>> stock_supplier.reload()
    >>> stock_supplier.debit
    Decimal('0.00')
    >>> stock_supplier.credit
    Decimal('50.00')
    >>> stock.reload()
    >>> stock.debit
    Decimal('50.00')
    >>> stock.credit
    Decimal('0.00')

Open supplier invoice::

    >>> Invoice = Model.get('account.invoice')
    >>> purchase.reload()
    >>> invoice, = purchase.invoices
    >>> invoice_line, = [l for l in invoice.lines if l.product == product]
    >>> invoice_line.unit_price = Decimal('6')
    >>> invoice_line, = [l for l in invoice.lines
    ...     if l.product == product_average]
    >>> invoice_line.unit_price = Decimal('4')
    >>> invoice.invoice_date = today
    >>> invoice.click('post')
    >>> invoice.state
    u'posted'
    >>> payable.reload()
    >>> payable.debit
    Decimal('0.00')
    >>> payable.credit
    Decimal('44.00')
    >>> expense.reload()
    >>> expense.debit
    Decimal('44.00')
    >>> expense.credit
    Decimal('0.00')

Sale 5 products::

    >>> Sale = Model.get('sale.sale')
    >>> sale = Sale()
    >>> sale.party = customer
    >>> sale.payment_term = payment_term
    >>> sale.invoice_method = 'shipment'
    >>> sale_line = sale.lines.new()
    >>> sale_line.product = product
    >>> sale_line.quantity = 2.0
    >>> sale_line = sale.lines.new()
    >>> sale_line.product = product_average
    >>> sale_line.quantity = 3.0
    >>> sale.click('quote')
    >>> sale.click('confirm')
    >>> sale.click('process')
    >>> sale.state
    u'processing'

Send 5 products::

    >>> shipment, = sale.shipments
    >>> shipment.click('assign_try')
    True
    >>> shipment.state
    u'assigned'
    >>> shipment.click('pack')
    >>> shipment.state
    u'packed'
    >>> shipment.click('done')
    >>> shipment.state
    u'done'
    >>> stock_customer.reload()
    >>> stock_customer.debit
    Decimal('28.00')
    >>> stock_customer.credit
    Decimal('0.00')
    >>> stock.reload()
    >>> stock.debit
    Decimal('50.00')
    >>> stock.credit
    Decimal('28.00')

Open customer invoice::

    >>> sale.reload()
    >>> invoice, = sale.invoices
    >>> invoice.click('post')
    >>> invoice.state
    u'posted'
    >>> receivable.reload()
    >>> receivable.debit
    Decimal('50.00')
    >>> receivable.credit
    Decimal('0.00')
    >>> revenue.reload()
    >>> revenue.debit
    Decimal('0.00')
    >>> revenue.credit
    Decimal('50.00')

Create an Inventory::

    >>> Inventory = Model.get('stock.inventory')
    >>> Location = Model.get('stock.location')
    >>> storage, = Location.find([
    ...         ('code', '=', 'STO'),
    ...         ])
    >>> inventory = Inventory()
    >>> inventory.location = storage
    >>> inventory.click('complete_lines')
    >>> inventory_line, = [l for l in inventory.lines if l.product == product]
    >>> inventory_line.quantity = 1.0
    >>> inventory_line, = [l for l in inventory.lines
    ...     if l.product == product_average]
    >>> inventory_line.quantity = 1.0
    >>> inventory.click('confirm')
    >>> inventory.state
    u'done'
    >>> stock_lost_found.reload()
    >>> stock_lost_found.debit
    Decimal('11.00')
    >>> stock_lost_found.credit
    Decimal('0.00')
    >>> stock.reload()
    >>> stock.debit
    Decimal('50.00')
    >>> stock.credit
    Decimal('39.00')

Create Drop Shipment Move::

    >>> ProductSupplier = Model.get('purchase.product_supplier')
    >>> product_supplier = ProductSupplier()
    >>> product_supplier.product = product.template
    >>> product_supplier.party = supplier
    >>> product_supplier.drop_shipment = True
    >>> product_supplier.delivery_time = 0
    >>> product_supplier.save()
    >>> product.template.supply_on_sale = True
    >>> product.template.save()

    >>> sale = Sale()
    >>> sale.party = customer
    >>> sale.payment_term = payment_term
    >>> sale_line = sale.lines.new()
    >>> sale_line.product = product
    >>> sale_line.quantity = 3
    >>> sale.click('quote')
    >>> sale.click('confirm')
    >>> sale.click('process')
    >>> sale.state
    u'processing'

    >>> PurchaseRequest = Model.get('purchase.request')
    >>> purchase_request, = PurchaseRequest.find()
    >>> create_purchase = Wizard('purchase.request.create_purchase',
    ...     [purchase_request])
    >>> purchase = purchase_request.purchase
    >>> purchase.payment_term = payment_term
    >>> purchase_line, = purchase.lines
    >>> purchase_line.unit_price = Decimal(6)
    >>> purchase.click('quote')
    >>> purchase.click('confirm')
    >>> purchase.click('process')
    >>> purchase.state
    u'processing'

    >>> shipment, = sale.drop_shipments
    >>> shipment.click('ship')
    >>> shipment.click('done')
    >>> shipment.state
    u'done'

    >>> stock_supplier.reload()
    >>> stock_supplier.debit
    Decimal('0.00')
    >>> stock_supplier.credit
    Decimal('68.00')
    >>> stock_customer.reload()
    >>> stock_customer.debit
    Decimal('46.00')
    >>> stock_customer.credit
    Decimal('0.00')

    >>> product_supplier = ProductSupplier()
    >>> product_supplier.product = product_average.template
    >>> product_supplier.party = supplier
    >>> product_supplier.drop_shipment = True
    >>> product_supplier.delivery_time = 0
    >>> product_supplier.save()
    >>> product_average.template.supply_on_sale = True
    >>> product_average.template.save()

    >>> sale = Sale()
    >>> sale.party = customer
    >>> sale.payment_term = payment_term
    >>> sale_line = sale.lines.new()
    >>> sale_line.product = product_average
    >>> sale_line.quantity = 4
    >>> sale.click('quote')
    >>> sale.click('confirm')
    >>> sale.click('process')
    >>> sale.state
    u'processing'

    >>> purchase_request, = [p for p in PurchaseRequest.find()
    ...     if p.state == 'draft']
    >>> create_purchase = Wizard('purchase.request.create_purchase',
    ...     [purchase_request])
    >>> purchase = purchase_request.purchase
    >>> purchase.payment_term = payment_term
    >>> purchase_line, = purchase.lines
    >>> purchase_line.unit_price = Decimal(5)
    >>> purchase.click('quote')
    >>> purchase.click('confirm')
    >>> purchase.click('process')
    >>> purchase.state
    u'processing'

    >>> shipment, = sale.drop_shipments
    >>> shipment.click('ship')
    >>> shipment.click('done')
    >>> shipment.state
    u'done'

    >>> stock_supplier.reload()
    >>> stock_supplier.debit
    Decimal('0.00')
    >>> stock_supplier.credit
    Decimal('88.00')
    >>> stock_customer.reload()
    >>> stock_customer.debit
    Decimal('66.00')
    >>> stock_customer.credit
    Decimal('0.00')
