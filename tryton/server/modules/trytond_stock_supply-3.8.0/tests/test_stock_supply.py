# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import unittest
import doctest
import datetime
from decimal import Decimal
import trytond.tests.test_tryton
from trytond.tests.test_tryton import ModuleTestCase
from trytond.tests.test_tryton import POOL, DB_NAME, USER, CONTEXT
from trytond.tests.test_tryton import doctest_setup, doctest_teardown
from trytond.transaction import Transaction

DATES = [
    # purchase date, delivery time, supply date
    (datetime.date(2011, 11, 21), 10, datetime.date(2011, 12, 1)),
    (datetime.date(2011, 11, 21), 9, datetime.date(2011, 11, 30)),
    (datetime.date(2011, 11, 21), 8, datetime.date(2011, 11, 29)),
    (datetime.date(2011, 11, 21), 7, datetime.date(2011, 11, 28)),
    (datetime.date(2011, 11, 21), 6, datetime.date(2011, 11, 27)),
    (datetime.date(2011, 11, 21), 5, datetime.date(2011, 11, 26)),
    (datetime.date(2011, 11, 21), 4, datetime.date(2011, 11, 25)),
    ]


class StockSupplyTestCase(ModuleTestCase):
    'Test StockSupply module'
    module = 'stock_supply'

    def setUp(self):
        super(StockSupplyTestCase, self).setUp()
        self.uom = POOL.get('product.uom')
        self.uom_category = POOL.get('product.uom.category')
        self.category = POOL.get('product.category')
        self.template = POOL.get('product.template')
        self.product = POOL.get('product.product')
        self.company = POOL.get('company.company')
        self.party = POOL.get('party.party')
        self.account = POOL.get('account.account')
        self.product_supplier = POOL.get('purchase.product_supplier')
        self.user = POOL.get('res.user')

    def test0010compute_supply_date(self):
        'Test compute_supply_date'
        for purchase_date, delivery_time, supply_date in DATES:
            with Transaction().start(DB_NAME, USER, context=CONTEXT):
                product_supplier = self.create_product_supplier(delivery_time)
                date = self.product_supplier.compute_supply_date(
                    product_supplier, purchase_date)
                self.assertEqual(date, supply_date)

    def test0020compute_purchase_date(self):
        'Test compute_purchase_date'
        for purchase_date, delivery_time, supply_date in DATES:
            with Transaction().start(DB_NAME, USER, context=CONTEXT):
                product_supplier = self.create_product_supplier(delivery_time)
                date = self.product_supplier.compute_purchase_date(
                    product_supplier, supply_date)
                self.assertEqual(date, purchase_date)

    def create_product_supplier(self, delivery_time):
        '''
        Create a Product with a Product Supplier

        :param delivery_time: time in days needed to supply
        :return: the id of the Product Supplier
        '''
        uom_category, = self.uom_category.create([{'name': 'Test'}])
        uom, = self.uom.create([{
                    'name': 'Test',
                    'symbol': 'T',
                    'category': uom_category.id,
                    'rate': 1.0,
                    'factor': 1.0,
                    }])
        category, = self.category.create([{'name': 'ProdCategoryTest'}])
        template, = self.template.create([{
                    'name': 'ProductTest',
                    'default_uom': uom.id,
                    'category': category.id,
                    'account_category': True,
                    'list_price': Decimal(0),
                    'cost_price': Decimal(0),
                    }])
        product, = self.product.create([{
                    'template': template.id,
                    }])
        company, = self.company.search([
                ('rec_name', '=', 'Dunder Mifflin'),
                ])
        self.user.write([self.user(USER)], {
            'main_company': company.id,
            'company': company.id,
            })
        receivable, = self.account.search([
            ('kind', '=', 'receivable'),
            ('company', '=', company.id),
            ])
        payable, = self.account.search([
            ('kind', '=', 'payable'),
            ('company', '=', company.id),
            ])
        supplier, = self.party.create([{
                    'name': 'supplier',
                    'account_receivable': receivable.id,
                    'account_payable': payable.id,
                    }])
        product_supplier, = self.product_supplier.create([{
                    'product': template.id,
                    'company': company.id,
                    'party': supplier.id,
                    'delivery_time': delivery_time,
                    }])
        return product_supplier


def suite():
    suite = trytond.tests.test_tryton.suite()
    from trytond.modules.company.tests import test_company
    for test in test_company.suite():
        if test not in suite and not isinstance(test, doctest.DocTestCase):
            suite.addTest(test)
    from trytond.modules.account.tests import test_account
    for test in test_account.suite():
        if test not in suite and not isinstance(test, doctest.DocTestCase):
            suite.addTest(test)
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        StockSupplyTestCase))
    suite.addTests(doctest.DocFileSuite('scenario_stock_internal_supply.rst',
            setUp=doctest_setup, tearDown=doctest_teardown, encoding='utf-8',
            optionflags=doctest.REPORT_ONLY_FIRST_FAILURE))
    suite.addTests(doctest.DocFileSuite(
            'scenario_stock_supply_purchase_request.rst',
            setUp=doctest_setup, tearDown=doctest_teardown, encoding='utf-8',
            optionflags=doctest.REPORT_ONLY_FIRST_FAILURE))
    return suite
