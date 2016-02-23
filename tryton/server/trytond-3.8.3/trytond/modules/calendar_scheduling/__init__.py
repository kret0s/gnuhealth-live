# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from . import caldav
from .calendar_ import *
from .res import *


def register():
    Pool.register(
        Event,
        EventAttendee,
        User,
        module='calendar_scheduling', type_='model')
