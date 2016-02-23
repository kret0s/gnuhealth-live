# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from sql import Column
from sql.aggregate import Max
from sql.conditionals import Coalesce
from sql.functions import Trim, Substring

from trytond.model import ModelView, ModelSQL, fields
from trytond.wizard import Wizard, StateAction
from trytond.pyson import PYSONEncoder
from trytond.pool import Pool
from trytond.transaction import Transaction

__all__ = ['ProductCostHistory', 'OpenProductCostHistory']


class ProductCostHistory(ModelSQL, ModelView):
    'History of Product Cost'
    __name__ = 'product.product.cost_history'
    _rec_name = 'date'
    template = fields.Many2One('product.template', 'Product')
    date = fields.DateTime('Date')
    cost_price = fields.Numeric('Cost Price')

    @classmethod
    def __setup__(cls):
        super(ProductCostHistory, cls).__setup__()
        cls._order.insert(0, ('date', 'DESC'))

    @classmethod
    def table_query(cls):
        pool = Pool()
        Property = pool.get('ir.property')
        Field = pool.get('ir.model.field')
        property_history = Property.__table_history__()
        field = Field.__table__()
        return property_history.join(field,
            condition=field.id == property_history.field
            ).select(Max(Column(property_history, '__id')).as_('id'),
                Max(property_history.create_uid).as_('create_uid'),
                Max(property_history.create_date).as_('create_date'),
                Max(property_history.write_uid).as_('write_uid'),
                Max(property_history.write_date).as_('write_date'),
                Coalesce(property_history.write_date,
                    property_history.create_date).as_('date'),
                Trim(Substring(property_history.res, ',.*'), 'LEADING', ','
                    ).cast(cls.template.sql_type().base).as_('template'),
                Trim(property_history.value, 'LEADING', ','
                    ).cast(cls.cost_price.sql_type().base).as_('cost_price'),
                where=(field.name == 'cost_price')
                & property_history.res.like('product.template,%'),
                group_by=(property_history.id,
                    Coalesce(property_history.write_date,
                        property_history.create_date),
                    property_history.res, property_history.value))


class OpenProductCostHistory(Wizard):
    'Open Product Cost History'
    __name__ = 'product.product.cost_history.open'
    start_state = 'open'
    open = StateAction('product_cost_history.act_product_cost_history_form')

    def do_open(self, action):
        pool = Pool()
        Product = pool.get('product.product')

        active_id = Transaction().context.get('active_id')
        if not active_id or active_id < 0:
            action['pyson_domain'] = PYSONEncoder().encode([
                    ('template', '=', None),
                    ])
        else:
            product = Product(active_id)
            action['pyson_domain'] = PYSONEncoder().encode([
                    ('template', '=', product.template.id),
                    ])
        return action, {}
