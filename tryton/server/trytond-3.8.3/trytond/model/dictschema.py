# This file is part of Tryton.  The COPYRIGHT file at the toplevel of this
# repository contains the full copyright notices and license terms.
from collections import OrderedDict
try:
    import simplejson as json
except ImportError:
    import json

from trytond.model import fields
from trytond.pyson import Eval
from trytond.rpc import RPC
from trytond.transaction import Transaction
from trytond.pool import Pool


class DictSchemaMixin(object):
    _rec_name = 'string'
    name = fields.Char('Name', required=True)
    string = fields.Char('String', translate=True, required=True)
    type_ = fields.Selection([
            ('boolean', 'Boolean'),
            ('integer', 'Integer'),
            ('char', 'Char'),
            ('float', 'Float'),
            ('numeric', 'Numeric'),
            ('date', 'Date'),
            ('datetime', 'DateTime'),
            ('selection', 'Selection'),
            ], 'Type', required=True)
    digits = fields.Integer('Digits', states={
            'invisible': ~Eval('type_').in_(['float', 'numeric']),
            }, depends=['type_'])
    selection = fields.Text('Selection', states={
            'invisible': Eval('type_') != 'selection',
            }, translate=True, depends=['type_'],
        help='A couple of key and label separated by ":" per line')
    selection_sorted = fields.Boolean('Selection Sorted', states={
            'invisible': Eval('type_') != 'selection',
            }, depends=['type_'],
        help='If the selection must be sorted on label')
    selection_json = fields.Function(fields.Char('Selection JSON',
            states={
                'invisible': Eval('type_') != 'selection',
                },
            depends=['type_']), 'get_selection_json')

    @classmethod
    def __setup__(cls):
        super(DictSchemaMixin, cls).__setup__()
        cls.__rpc__.update({
                'get_keys': RPC(instantiate=0),
                })

    @staticmethod
    def default_digits():
        return 2

    @staticmethod
    def default_selection_sorted():
        return True

    def get_selection_json(self, name):
        db_selection = self.selection or ''
        selection = [[w.strip() for w in v.split(':', 1)]
            for v in db_selection.splitlines() if v]
        return json.dumps(selection)

    @classmethod
    def get_keys(cls, records):
        pool = Pool()
        Config = pool.get('ir.configuration')
        keys = []
        for record in records:
            new_key = {
                'id': record.id,
                'name': record.name,
                'string': record.string,
                'type_': record.type_,
                }
            if record.type_ == 'selection':
                with Transaction().set_context(language=Config.get_language()):
                    english_key = cls(record.id)
                    selection = OrderedDict(json.loads(
                            english_key.selection_json))
                selection.update(dict(json.loads(record.selection_json)))
                new_key['selection'] = selection.items()
                new_key['sorted'] = record.selection_sorted
            elif record.type_ in ('float', 'numeric'):
                new_key['digits'] = (16, record.digits)
            keys.append(new_key)
        return keys
