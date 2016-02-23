# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from .calendar_ import *


def register():
    Pool.register(
        Event,
        module='calendar_classification', type_='model')
