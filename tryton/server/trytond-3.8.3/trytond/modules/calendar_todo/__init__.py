# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from . import caldav
from .todo import *
from .webdav import *


def register():
    Pool.register(
        Todo,
        TodoCategory,
        TodoRDate,
        TodoRRule,
        TodoExDate,
        TodoExRule,
        TodoAttendee,
        TodoAlarm,
        Collection,
        module='calendar_todo', type_='model')
