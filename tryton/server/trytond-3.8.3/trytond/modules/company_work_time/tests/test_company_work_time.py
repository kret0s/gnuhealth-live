# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import unittest
import trytond.tests.test_tryton
from trytond.tests.test_tryton import ModuleTestCase


class CompanyWorkTimeTestCase(ModuleTestCase):
    'Test CompanyWorkTime module'
    module = 'company_work_time'


def suite():
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        CompanyWorkTimeTestCase))
    return suite
