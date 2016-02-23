# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from decimal import Decimal
from trytond.model import Workflow, ModelView, fields, Check
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

__all__ = ['Move']
__metaclass__ = PoolMeta


class Move:
    __name__ = 'stock.move'
    fifo_quantity = fields.Float('FIFO Quantity')

    @classmethod
    def __setup__(cls):
        super(Move, cls).__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('check_fifo_quantity_out',
                Check(t, t.quantity >= t.fifo_quantity),
                'FIFO quantity can not be greater than quantity.'),
            ]
        cls._error_messages.update({
                'del_move_fifo': ('You can not delete move "%s" that is used '
                    'for FIFO cost price.'),
                })

    @staticmethod
    def default_fifo_quantity():
        return 0.0

    def _update_fifo_out_product_cost_price(self):
        '''
        Update the product cost price of the given product on the move. Update
        fifo_quantity on the concerned incomming moves. Return the
        cost price for outputing the given product and quantity.
        '''
        pool = Pool()
        Uom = pool.get('product.uom')
        Currency = pool.get('currency.currency')

        total_qty = Uom.compute_qty(self.uom, self.quantity,
            self.product.default_uom, round=False)

        fifo_moves = self.product.template.get_fifo_move(total_qty)

        cost_price = Decimal("0.0")
        consumed_qty = 0.0
        for move, move_qty in fifo_moves:
            consumed_qty += move_qty

            with Transaction().set_context(date=move.effective_date):
                move_unit_price = Currency.compute(
                    move.currency, move.unit_price,
                    self.company.currency, round=False)
            move_unit_price = Uom.compute_price(move.uom, move_unit_price,
                    move.product.default_uom)
            cost_price += move_unit_price * Decimal(str(move_qty))

            move.quantity = move_qty
            move._update_product_cost_price('out')

            move_qty = Uom.compute_qty(self.product.default_uom, move_qty,
                    move.uom, round=False)
            # Use write as move instance quantity was modified to call
            # _update_product_cost_price
            self.write([self.__class__(move.id)], {
                    'fifo_quantity': (move.fifo_quantity or 0.0) + move_qty,
                    })

        if Decimal(str(consumed_qty)) != Decimal("0"):
            cost_price = cost_price / Decimal(str(consumed_qty))

        if cost_price != Decimal("0"):
            digits = self.__class__.cost_price.digits
            return cost_price.quantize(
                Decimal(str(10.0 ** -digits[1])))
        else:
            return self.product.cost_price

    def _do(self):
        if (self.from_location.type in ('supplier', 'production')
                and self.to_location.type == 'storage'
                and self.product.cost_price_method == 'fifo'):
            self._update_product_cost_price('in')
        elif (self.to_location.type == 'supplier'
                and self.from_location.type == 'storage'
                and self.product.cost_price_method == 'fifo'):
            self._update_product_cost_price('out')
        elif (self.from_location.type == 'storage'
                and self.to_location.type != 'storage'
                and self.product.cost_price_method == 'fifo'):
            cost_price = self._update_fifo_out_product_cost_price()
            if self.cost_price is None:
                self.cost_price = cost_price
        super(Move, self)._do()

    @classmethod
    @ModelView.button
    @Workflow.transition('cancel')
    def cancel(cls, moves):
        pass

    @classmethod
    def delete(cls, moves):
        fifo_moves = cls.search([
                ('id', 'in', [m.id for m in moves]),
                ('fifo_quantity', '!=', 0.0),
                ])
        if fifo_moves:
            cls.raise_user_error('del_move_fifo', (fifo_moves[0].rec_name,))
        super(Move, cls).delete(moves)
