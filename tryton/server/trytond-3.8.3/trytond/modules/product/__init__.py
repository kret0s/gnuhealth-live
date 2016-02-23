# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from .uom import *
from .category import *
from .product import *


def register():
    Pool.register(
        UomCategory,
        Uom,
        Category,
        Template,
        Product,
        module='product', type_='model')
