# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from .product import *
from .configuration import *


def register():
    Pool.register(
        Category,
        CategoryCustomerTax,
        CategorySupplierTax,
        Template,
        TemplateCustomerTax,
        TemplateSupplierTax,
        Configuration,
        module='account_product', type_='model')
