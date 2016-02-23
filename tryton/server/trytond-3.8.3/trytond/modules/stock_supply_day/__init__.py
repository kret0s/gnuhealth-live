# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from .purchase import *


def register():
    Pool.register(
        ProductSupplier,
        ProductSupplierDay,
        module='stock_supply_day', type_='model')
