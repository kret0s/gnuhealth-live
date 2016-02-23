# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from . import carddav
from .webdav import *
from .party import *


def register():
    Pool.register(
        Collection,
        Party,
        Address,
        ActionReport,
        module='party_vcarddav', type_='model')
    Pool.register(
        VCard,
        module='party_vcarddav', type_='report')
