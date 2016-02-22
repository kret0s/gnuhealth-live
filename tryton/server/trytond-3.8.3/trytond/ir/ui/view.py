# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import os
import sys
import logging
try:
    import simplejson as json
except ImportError:
    import json

from lxml import etree
from trytond.model import ModelView, ModelSQL, fields
from trytond import backend
from trytond.pyson import Eval, Bool, PYSONDecoder
from trytond.tools import file_open
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateView, Button
from trytond.pool import Pool
from trytond.cache import Cache
from trytond.rpc import RPC

__all__ = [
    'View', 'ShowViewStart', 'ShowView',
    'ViewTreeWidth', 'ViewTreeState', 'ViewSearch',
    ]

logger = logging.getLogger(__name__)


class View(ModelSQL, ModelView):
    "View"
    __name__ = 'ir.ui.view'
    _rec_name = 'model'
    model = fields.Char('Model', select=True, states={
            'required': Eval('type').in_([None, 'tree', 'form', 'graph']),
            })
    priority = fields.Integer('Priority', required=True, select=True)
    type = fields.Selection([
            (None, ''),
            ('tree', 'Tree'),
            ('form', 'Form'),
            ('graph', 'Graph'),
            ('calendar', 'Calendar'),
            ('board', 'Board'),
            ], 'View Type', select=True)
    data = fields.Text('Data')
    name = fields.Char('Name', states={
            'invisible': ~(Eval('module') & Eval('name')),
            }, depends=['module'], readonly=True)
    arch = fields.Function(fields.Text('View Architecture', states={
                'readonly': Bool(Eval('name')),
                }, depends=['name']), 'get_arch', setter='set_arch')
    inherit = fields.Many2One('ir.ui.view', 'Inherited View', select=True,
            ondelete='CASCADE')
    field_childs = fields.Char('Children Field', states={
            'invisible': Eval('type') != 'tree',
            }, depends=['type'])
    module = fields.Char('Module', states={
            'invisible': ~Eval('module'),
            }, readonly=True)
    domain = fields.Char('Domain', states={
            'invisible': ~Eval('inherit'),
            }, depends=['inherit'])
    _get_rng_cache = Cache('ir_ui_view.get_rng')

    @classmethod
    def __setup__(cls):
        super(View, cls).__setup__()
        cls._error_messages.update({
                'invalid_xml': 'Invalid XML for view "%s".',
                })
        cls._order.insert(0, ('priority', 'ASC'))
        cls._buttons.update({
                'show': {
                    'readonly': Eval('type') != 'form',
                    },
                })

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().cursor
        table = TableHandler(cursor, cls, module_name)

        # Migration from 2.4 arch moved into data
        if table.column_exist('arch'):
            table.column_rename('arch', 'data')

        super(View, cls).__register__(module_name)

        # New instance to refresh definition
        table = TableHandler(cursor, cls, module_name)

        # Migration from 1.0 arch no more required
        table.not_null_action('arch', action='remove')

        # Migration from 2.4 model no more required
        table.not_null_action('model', action='remove')

    @staticmethod
    def default_priority():
        return 16

    @staticmethod
    def default_module():
        return Transaction().context.get('module') or ''

    @classmethod
    @ModelView.button_action('ir.act_view_show')
    def show(cls, views):
        pass

    @classmethod
    def get_rng(cls, type_):
        key = (cls.__name__, type_)
        rng = cls._get_rng_cache.get(key)
        if rng is None:
            rng_name = os.path.join(os.path.dirname(
                    unicode(__file__, sys.getfilesystemencoding())),
                type_ + '.rng')
            rng = etree.fromstring(open(rng_name).read())
            cls._get_rng_cache.set(key, rng)
        return rng

    @classmethod
    def validate(cls, views):
        super(View, cls).validate(views)
        cls.check_xml(views)

    @classmethod
    def check_xml(cls, views):
        "Check XML"
        for view in views:
            if not view.arch:
                continue
            xml = view.arch.strip()
            if not xml:
                continue
            tree = etree.fromstring(xml)

            if hasattr(etree, 'RelaxNG'):
                rng_type = view.inherit.type if view.inherit else view.type
                validator = etree.RelaxNG(etree=cls.get_rng(rng_type))
                if not validator.validate(tree):
                    error_log = reduce(lambda x, y: str(x) + '\n' + str(y),
                            validator.error_log.filter_from_errors())
                    logger.error('Invalid xml view:\n%s',
                        str(error_log) + '\n' + xml)
                    cls.raise_user_error('invalid_xml', (view.rec_name,))
            root_element = tree.getroottree().getroot()

            # validate pyson attributes
            validates = {
                'states': fields.states_validate,
            }

            def encode(element):
                for attr in ('states', 'domain', 'spell'):
                    if element.get(attr):
                        try:
                            value = PYSONDecoder().decode(element.get(attr))
                            validates.get(attr, lambda a: True)(value)
                        except Exception, e:
                            logger.error('Invalid pyson view element "%s:%s":'
                                '\n%s\n%s',
                                element.get('id') or element.get('name'), attr,
                                str(e), xml)
                            return False
                for child in element:
                    if not encode(child):
                        return False
                return True
            if not encode(root_element):
                cls.raise_user_error('invalid_xml', (view.rec_name,))

    def get_arch(self, name):
        value = None
        if self.name and self.module:
            path = os.path.join(self.module, 'view', self.name + '.xml')
            try:
                with file_open(path, subdir='modules') as fp:
                    value = fp.read()
            except IOError:
                pass
        if not value:
            value = self.data
        return value

    @classmethod
    def set_arch(cls, views, name, value):
        cls.write(views, {'data': value})

    @classmethod
    def delete(cls, views):
        super(View, cls).delete(views)
        # Restart the cache
        ModelView._fields_view_get_cache.clear()

    @classmethod
    def create(cls, vlist):
        views = super(View, cls).create(vlist)
        # Restart the cache
        ModelView._fields_view_get_cache.clear()
        return views

    @classmethod
    def write(cls, views, values, *args):
        super(View, cls).write(views, values, *args)
        # Restart the cache
        ModelView._fields_view_get_cache.clear()


class ShowViewStart(ModelView):
    'Show view'
    __name__ = 'ir.ui.view.show.start'


class ShowView(Wizard):
    'Show view'
    __name__ = 'ir.ui.view.show'

    class ShowStateView(StateView):

        def __init__(self, model_name, buttons):
            StateView.__init__(self, model_name, None, buttons)

        def get_view(self, wizard, state_name):
            pool = Pool()
            View = pool.get('ir.ui.view')
            view = View(Transaction().context.get('active_id'))
            Model = pool.get(view.model)
            return Model.fields_view_get(view_id=view.id)

        def get_defaults(self, wizard, state_name, fields):
            return {}

    start = ShowStateView('ir.ui.view.show.start', [
            Button('Close', 'end', 'tryton-close', default=True),
            ])


class ViewTreeWidth(ModelSQL, ModelView):
    "View Tree Width"
    __name__ = 'ir.ui.view_tree_width'
    _rec_name = 'model'
    model = fields.Char('Model', required=True, select=True)
    field = fields.Char('Field', required=True, select=True)
    user = fields.Many2One('res.user', 'User', required=True,
            ondelete='CASCADE', select=True)
    width = fields.Integer('Width', required=True)

    @classmethod
    def __setup__(cls):
        super(ViewTreeWidth, cls).__setup__()
        cls.__rpc__.update({
                'set_width': RPC(readonly=False),
                })

    @classmethod
    def delete(cls, records):
        ModelView._fields_view_get_cache.clear()
        super(ViewTreeWidth, cls).delete(records)

    @classmethod
    def create(cls, vlist):
        res = super(ViewTreeWidth, cls).create(vlist)
        ModelView._fields_view_get_cache.clear()
        return res

    @classmethod
    def write(cls, records, values, *args):
        super(ViewTreeWidth, cls).write(records, values, *args)
        ModelView._fields_view_get_cache.clear()

    @classmethod
    def set_width(cls, model, fields):
        '''
        Set width for the current user on the model.
        fields is a dictionary with key: field name and value: width.
        '''
        records = cls.search([
            ('user', '=', Transaction().user),
            ('model', '=', model),
            ('field', 'in', fields.keys()),
            ])
        cls.delete(records)

        to_create = []
        for field in fields.keys():
            to_create.append({
                    'model': model,
                    'field': field,
                    'user': Transaction().user,
                    'width': fields[field],
                    })
        if to_create:
            cls.create(to_create)


class ViewTreeState(ModelSQL, ModelView):
    'View Tree State'
    __name__ = 'ir.ui.view_tree_state'
    _rec_name = 'model'
    model = fields.Char('Model', required=True)
    domain = fields.Char('Domain', required=True)
    user = fields.Many2One('res.user', 'User', required=True,
            ondelete='CASCADE')
    child_name = fields.Char('Child Name')
    nodes = fields.Text('Expanded Nodes')
    selected_nodes = fields.Text('Selected Nodes')

    @classmethod
    def __setup__(cls):
        super(ViewTreeState, cls).__setup__()
        cls.__rpc__.update({
                'set': RPC(readonly=False, check_access=False),
                'get': RPC(check_access=False),
                })

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().cursor
        table = TableHandler(cursor, cls, module_name)

        # Migration from 2.8: table name changed
        table.table_rename(cursor, 'ir_ui_view_tree_expanded_state',
            cls._table)

        super(ViewTreeState, cls).__register__(module_name)

        table = TableHandler(cursor, cls, module_name)
        table.index_action(['model', 'domain', 'user', 'child_name'], 'add')

    @staticmethod
    def default_nodes():
        return '[]'

    @staticmethod
    def default_selected_nodes():
        return '[]'

    @classmethod
    def set(cls, model, domain, child_name, nodes, selected_nodes):
        # Normalize the json domain
        domain = json.dumps(json.loads(domain))
        current_user = Transaction().user
        records = cls.search([
                ('user', '=', current_user),
                ('model', '=', model),
                ('domain', '=', domain),
                ('child_name', '=', child_name),
                ])
        cls.delete(records)
        cls.create([{
                    'user': current_user,
                    'model': model,
                    'domain': domain,
                    'child_name': child_name,
                    'nodes': nodes,
                    'selected_nodes': selected_nodes,
                    }])

    @classmethod
    def get(cls, model, domain, child_name):
        # Normalize the json domain
        domain = json.dumps(json.loads(domain))
        current_user = Transaction().user
        try:
            expanded_info, = cls.search([
                    ('user', '=', current_user),
                    ('model', '=', model),
                    ('domain', '=', domain),
                    ('child_name', '=', child_name),
                    ],
                limit=1)
        except ValueError:
            return (cls.default_nodes(), cls.default_selected_nodes())
        state = cls(expanded_info)
        return (state.nodes or cls.default_nodes(),
            state.selected_nodes or cls.default_selected_nodes())


class ViewSearch(ModelSQL, ModelView):
    "View Search"
    __name__ = 'ir.ui.view_search'

    name = fields.Char('Name', required=True)
    model = fields.Char('Model', required=True)
    domain = fields.Char('Domain', help="The PYSON domain")
    user = fields.Many2One('res.user', 'User', required=True,
        ondelete='CASCADE')

    @classmethod
    def __setup__(cls):
        super(ViewSearch, cls).__setup__()
        cls.__rpc__.update({
                'get_search': RPC(),
                })

    @staticmethod
    def default_user():
        return Transaction().user

    @classmethod
    def get_search(cls, user_id=None):
        if user_id is None:
            user_id = Transaction().user
        decoder = PYSONDecoder()
        searches = cls.search([
                ('user', '=', user_id),
                ], order=[('model', 'ASC'), ('name', 'ASC')])
        result = {}
        for search in searches:
            result.setdefault(search.model, []).append(
                (search.id, search.name, decoder.decode(search.domain)))
        return result
