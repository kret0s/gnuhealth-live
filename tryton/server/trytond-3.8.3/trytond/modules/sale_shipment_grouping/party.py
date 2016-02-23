# This file is part of Tryton.  The COPYRIGHT file at the top level of this
# repository contains the full copyright notices and license terms.

from trytond.model import fields
from trytond.pool import PoolMeta

__all__ = ['Party']
__metaclass__ = PoolMeta


class Party:
    __name__ = 'party.party'

    sale_shipment_grouping_method = fields.Property(fields.Selection([
                (None, 'None'),
                ('standard', 'Standard'),
                ],
            'Sale Shipment Grouping Method'))
