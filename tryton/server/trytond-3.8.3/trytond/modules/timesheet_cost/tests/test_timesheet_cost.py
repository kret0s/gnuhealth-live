# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import unittest
import doctest
import datetime
from decimal import Decimal

import trytond.tests.test_tryton
from trytond.tests.test_tryton import ModuleTestCase
from trytond.tests.test_tryton import POOL, DB_NAME, USER, CONTEXT
from trytond.transaction import Transaction


class TimesheetCostTestCase(ModuleTestCase):
    'Test TimesheetCost module'
    module = 'timesheet_cost'

    def setUp(self):
        super(TimesheetCostTestCase, self).setUp()
        self.party = POOL.get('party.party')
        self.employee = POOL.get('company.employee')
        self.employee_cost_price = POOL.get('company.employee_cost_price')
        self.company = POOL.get('company.company')
        self.work = POOL.get('timesheet.work')
        self.line = POOL.get('timesheet.line')

    def test0010compute_cost_price(self):
        'Test compute_cost_price'
        cost_prices = [
            (datetime.date(2011, 1, 1), Decimal(10)),
            (datetime.date(2012, 1, 1), Decimal(15)),
            (datetime.date(2013, 1, 1), Decimal(20)),
            ]
        test_prices = [
            (datetime.date(2010, 1, 1), 0),
            (datetime.date(2011, 1, 1), Decimal(10)),
            (datetime.date(2011, 6, 1), Decimal(10)),
            (datetime.date(2012, 1, 1), Decimal(15)),
            (datetime.date(2012, 6, 1), Decimal(15)),
            (datetime.date(2013, 1, 1), Decimal(20)),
            (datetime.date(2013, 6, 1), Decimal(20)),
            ]
        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            company, = self.company.search([
                    ('rec_name', '=', 'Dunder Mifflin'),
                    ])
            party = self.party(name='Pam Beesly')
            party.save()
            employee = self.employee(party=party.id,
                company=company)
            employee.save()
            for date, cost_price in cost_prices:
                self.employee_cost_price(
                    employee=employee,
                    date=date,
                    cost_price=cost_price).save()
            for date, cost_price in test_prices:
                self.assertEqual(employee.compute_cost_price(date), cost_price)


def suite():
    suite = trytond.tests.test_tryton.suite()
    from trytond.modules.company.tests import test_company
    for test in test_company.suite():
        if test not in suite and not isinstance(test, doctest.DocTestCase):
            suite.addTest(test)
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        TimesheetCostTestCase))
    return suite
