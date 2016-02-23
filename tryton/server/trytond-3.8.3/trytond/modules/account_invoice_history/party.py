# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.pool import PoolMeta

__all__ = ['Party', 'Address']
__metaclass__ = PoolMeta


class Party:
    __name__ = 'party.party'
    _history = True


class Address:
    __name__ = 'party.address'
    _history = True
