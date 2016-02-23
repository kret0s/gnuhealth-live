# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from .purchase import *
from .product import *
from .stock import *
from .configuration import *
from .invoice import *


def register():
    Pool.register(
        Move,
        Purchase,
        PurchaseIgnoredInvoice,
        PurchaseRecreadtedInvoice,
        PurchaseLine,
        PurchaseLineTax,
        PurchaseLineIgnoredMove,
        PurchaseLineRecreatedMove,
        Template,
        Product,
        ProductSupplier,
        ProductSupplierPrice,
        ShipmentIn,
        ShipmentInReturn,
        HandleShipmentExceptionAsk,
        HandleInvoiceExceptionAsk,
        Configuration,
        Invoice,
        InvoiceLine,
        module='purchase', type_='model')
    Pool.register(
        PurchaseReport,
        module='purchase', type_='report')
    Pool.register(
        OpenSupplier,
        HandleShipmentException,
        HandleInvoiceException,
        OpenProductQuantitiesByWarehouse,
        module='purchase', type_='wizard')
