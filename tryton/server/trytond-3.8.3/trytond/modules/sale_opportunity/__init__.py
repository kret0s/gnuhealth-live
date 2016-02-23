# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from .opportunity import *
from .configuration import *
from .sale import *


def register():
    Pool.register(
        SaleOpportunity,
        SaleOpportunityLine,
        SaleOpportunityHistory,
        SaleOpportunityEmployee,
        OpenSaleOpportunityEmployeeStart,
        SaleOpportunityMonthly,
        SaleOpportunityEmployeeMonthly,
        Configuration,
        Sale,
        module='sale_opportunity', type_='model')
    Pool.register(
        OpenSaleOpportunityEmployee,
        module='sale_opportunity', type_='wizard')
