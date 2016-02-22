# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import base64
import os
from operator import itemgetter
from collections import defaultdict
from functools import partial

from sql import Table
from sql.aggregate import Count

from ..model import ModelView, ModelStorage, ModelSQL, fields
from ..tools import file_open
from .. import backend
from ..pyson import PYSONDecoder, PYSON
from ..transaction import Transaction
from ..pool import Pool
from ..cache import Cache
from ..rpc import RPC

__all__ = [
    'Action', 'ActionKeyword', 'ActionReport',
    'ActionActWindow', 'ActionActWindowView', 'ActionActWindowDomain',
    'ActionWizard', 'ActionURL',
    ]

EMAIL_REFKEYS = set(('cc', 'to', 'subject'))


class Action(ModelSQL, ModelView):
    "Action"
    __name__ = 'ir.action'
    name = fields.Char('Name', required=True, translate=True)
    type = fields.Char('Type', required=True, readonly=True)
    usage = fields.Char('Usage')
    keywords = fields.One2Many('ir.action.keyword', 'action',
            'Keywords')
    groups = fields.Many2Many('ir.action-res.group', 'action', 'group',
            'Groups')
    icon = fields.Many2One('ir.ui.icon', 'Icon')
    active = fields.Boolean('Active', select=True)

    @classmethod
    def __setup__(cls):
        super(Action, cls).__setup__()
        cls.__rpc__.update({
                'get_action_id': RPC(),
                })

    @staticmethod
    def default_usage():
        return None

    @staticmethod
    def default_active():
        return True

    @classmethod
    def write(cls, actions, values, *args):
        pool = Pool()
        super(Action, cls).write(actions, values, *args)
        pool.get('ir.action.keyword')._get_keyword_cache.clear()

    @classmethod
    def get_action_id(cls, action_id):
        pool = Pool()
        with Transaction().set_context(active_test=False):
            if cls.search([
                        ('id', '=', action_id),
                        ]):
                return action_id
            for action_type in (
                    'ir.action.report',
                    'ir.action.act_window',
                    'ir.action.wizard',
                    'ir.action.url',
                    ):
                Action = pool.get(action_type)
                actions = Action.search([
                    ('id', '=', action_id),
                    ])
                if actions:
                    action, = actions
                    return action.action.id

    @classmethod
    def get_action_values(cls, type_, action_ids):
        Action = Pool().get(type_)
        columns = set(Action._fields.keys())
        columns.add('icon.rec_name')
        to_remove = ()
        if type_ == 'ir.action.report':
            to_remove = ('report_content_custom', 'report_content')
        elif type_ == 'ir.action.act_window':
            to_remove = ('domain', 'context', 'search_value')
        columns.difference_update(to_remove)
        return Action.read(action_ids, list(columns))


class ActionKeyword(ModelSQL, ModelView):
    "Action keyword"
    __name__ = 'ir.action.keyword'
    keyword = fields.Selection([
            ('tree_open', 'Open tree'),
            ('tree_action', 'Action tree'),
            ('form_print', 'Print form'),
            ('form_action', 'Action form'),
            ('form_relate', 'Form relate'),
            ('graph_open', 'Open Graph'),
            ], string='Keyword', required=True)
    model = fields.Reference('Model', selection='models_get')
    action = fields.Many2One('ir.action', 'Action',
        ondelete='CASCADE', select=True)
    groups = fields.Function(fields.One2Many('res.group', None, 'Groups'),
        'get_groups', searcher='search_groups')
    _get_keyword_cache = Cache('ir_action_keyword.get_keyword')

    @classmethod
    def __setup__(cls):
        super(ActionKeyword, cls).__setup__()
        cls.__rpc__.update({'get_keyword': RPC()})
        cls._error_messages.update({
                'wrong_wizard_model': ('Wrong wizard model in keyword action '
                    '"%s".'),
                })

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        super(ActionKeyword, cls).__register__(module_name)

        table = TableHandler(Transaction().cursor, cls, module_name)
        table.index_action(['keyword', 'model'], 'add')

    def get_groups(self, name):
        return [g.id for g in self.action.groups]

    @classmethod
    def search_groups(cls, name, clause):
        return [('action.groups',) + tuple(clause[1:])]

    @classmethod
    def validate(cls, actions):
        super(ActionKeyword, cls).validate(actions)
        for action in actions:
            action.check_wizard_model()

    def check_wizard_model(self):
        ActionWizard = Pool().get('ir.action.wizard')
        if self.action.type == 'ir.action.wizard':
            action_wizard, = ActionWizard.search([
                ('action', '=', self.action.id),
                ], limit=1)
            if action_wizard.model:
                if self.model.__name__ != action_wizard.model:
                    self.raise_user_error('wrong_wizard_model', (
                            action_wizard.rec_name,))

    @staticmethod
    def _convert_vals(vals):
        vals = vals.copy()
        pool = Pool()
        Action = pool.get('ir.action')
        if 'action' in vals:
            vals['action'] = Action.get_action_id(vals['action'])
        return vals

    @staticmethod
    def models_get():
        pool = Pool()
        Model = pool.get('ir.model')
        return [(m.model, m.name) for m in Model.search([])]

    @classmethod
    def delete(cls, keywords):
        ModelView._fields_view_get_cache.clear()
        ModelView._view_toolbar_get_cache.clear()
        cls._get_keyword_cache.clear()
        super(ActionKeyword, cls).delete(keywords)

    @classmethod
    def create(cls, vlist):
        ModelView._fields_view_get_cache.clear()
        ModelView._view_toolbar_get_cache.clear()
        cls._get_keyword_cache.clear()
        new_vlist = []
        for vals in vlist:
            new_vlist.append(cls._convert_vals(vals))
        return super(ActionKeyword, cls).create(new_vlist)

    @classmethod
    def write(cls, keywords, values, *args):
        actions = iter((keywords, values) + args)
        args = []
        for keywords, values in zip(actions, actions):
            args.extend((keywords, cls._convert_vals(values)))
        super(ActionKeyword, cls).write(*args)
        ModelView._fields_view_get_cache.clear()
        ModelView._view_toolbar_get_cache.clear()
        cls._get_keyword_cache.clear()

    @classmethod
    def get_keyword(cls, keyword, value):
        Action = Pool().get('ir.action')
        key = (keyword, tuple(value))
        keywords = cls._get_keyword_cache.get(key)
        if keywords is not None:
            return keywords
        keywords = []
        model, model_id = value

        clause = [
            ('keyword', '=', keyword),
            ('model', '=', model + ',-1'),
            ]
        if model_id >= 0:
            clause = ['OR',
                clause,
                [
                    ('keyword', '=', keyword),
                    ('model', '=', model + ',' + str(model_id)),
                    ],
                ]
        clause = [clause, ('action.active', '=', True)]
        action_keywords = cls.search(clause, order=[])
        types = defaultdict(list)
        for action_keyword in action_keywords:
            type_ = action_keyword.action.type
            types[type_].append(action_keyword.action.id)
        for type_, action_ids in types.iteritems():
            keywords.extend(Action.get_action_values(type_, action_ids))
        keywords.sort(key=itemgetter('name'))
        cls._get_keyword_cache.set(key, keywords)
        return keywords


class ActionMixin(ModelSQL):
    _order_name = 'action'
    _action_name = 'name'

    @classmethod
    def __setup__(cls):
        super(ActionMixin, cls).__setup__()
        for name in dir(Action):
            field = getattr(Action, name)
            if (isinstance(field, fields.Field)
                    and not getattr(cls, name, None)):
                setattr(cls, name, fields.Function(field, 'get_action',
                        setter='set_action', searcher='search_action'))
                default_func = 'default_' + name
                if getattr(Action, default_func, None):
                    setattr(cls, default_func,
                        partial(ActionMixin._default_action, name))

    @staticmethod
    def _default_action(name):
        pool = Pool()
        Action = pool.get('ir.action')
        return getattr(Action, 'default_' + name, None)()

    @classmethod
    def get_action(cls, ids, names):
        records = cls.browse(ids)
        result = {}
        for name in names:
            result[name] = values = {}
            for record in records:
                value = getattr(record, 'action')
                convert = lambda v: v
                if value is not None:
                    value = getattr(value, name)
                    if isinstance(value, ModelStorage):
                        if cls._fields[name]._type == 'reference':
                            convert = str
                        else:
                            convert = int
                    elif isinstance(value, (list, tuple)):
                        convert = lambda v: [r.id for r in v]
                values[record.id] = convert(value)
        return result

    @classmethod
    def set_action(cls, records, name, value):
        pool = Pool()
        Action = pool.get('ir.action')
        Action.write([r.action for r in records], {
                name: value,
                })

    @classmethod
    def search_action(cls, name, clause):
        return [('action.' + name,) + tuple(clause[1:])]

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        ModelView._fields_view_get_cache.clear()
        ModelView._view_toolbar_get_cache.clear()
        Action = pool.get('ir.action')
        ir_action = cls.__table__()
        new_records = []
        for values in vlist:
            later = {}
            action_values = {}
            values = values.copy()
            for field in values:
                if field in Action._fields:
                    action_values[field] = values[field]
                if hasattr(getattr(cls, field), 'set'):
                    later[field] = values[field]
            for field in later:
                del values[field]
            action_values['type'] = cls.default_type()
            cursor = Transaction().cursor
            if cursor.nextid(cls._table):
                cursor.setnextid(cls._table, cursor.currid(Action._table))
            if 'action' not in values:
                action, = Action.create([action_values])
                values['action'] = action.id
            else:
                action = Action(values['action'])
            record, = super(ActionMixin, cls).create([values])
            cursor.execute(*ir_action.update(
                    [ir_action.id], [action.id],
                    where=ir_action.id == record.id))
            cursor.update_auto_increment(cls._table, action.id)
            record = cls(action.id)
            new_records.append(record)
            cls.write([record], later)
        return new_records

    @classmethod
    def write(cls, records, values, *args):
        pool = Pool()
        ActionKeyword = pool.get('ir.action.keyword')
        super(ActionMixin, cls).write(records, values, *args)
        ModelView._fields_view_get_cache.clear()
        ModelView._view_toolbar_get_cache.clear()
        ActionKeyword._get_keyword_cache.clear()

    @classmethod
    def delete(cls, records):
        pool = Pool()
        ModelView._fields_view_get_cache.clear()
        ModelView._view_toolbar_get_cache.clear()
        Action = pool.get('ir.action')
        actions = [x.action for x in records]
        super(ActionMixin, cls).delete(records)
        Action.delete(actions)

    @classmethod
    def copy(cls, records, default=None):
        pool = Pool()
        Action = pool.get('ir.action')
        if default is None:
            default = {}
        default = default.copy()
        new_records = []
        for record in records:
            default['action'] = Action.copy([record.action])[0].id
            new_records.extend(super(ActionMixin, cls).copy([record],
                    default=default))
        return new_records

    @classmethod
    def get_groups(cls, name, action_id=None):
        # TODO add cache
        domain = [
            (cls._action_name, '=', name),
            ]
        if action_id:
            domain.append(('id', '=', action_id))
        actions = cls.search(domain)
        groups = {g.id for a in actions for g in a.groups}
        return groups


class ActionReport(ActionMixin, ModelSQL, ModelView):
    "Action report"
    __name__ = 'ir.action.report'
    _action_name = 'report_name'
    model = fields.Char('Model')
    report_name = fields.Char('Internal Name', required=True)
    report = fields.Char('Path')
    report_content_custom = fields.Binary('Content')
    report_content = fields.Function(fields.Binary('Content',
            filename='report_content_name'),
        'get_report_content', setter='set_report_content')
    report_content_name = fields.Function(fields.Char('Content Name',
            on_change_with=['name', 'template_extension']),
        'on_change_with_report_content_name')
    action = fields.Many2One('ir.action', 'Action', required=True,
            ondelete='CASCADE')
    direct_print = fields.Boolean('Direct Print')
    template_extension = fields.Selection([
            ('odt', 'OpenDocument Text'),
            ('odp', 'OpenDocument Presentation'),
            ('ods', 'OpenDocument Spreadsheet'),
            ('odg', 'OpenDocument Graphics'),
            ], string='Template Extension', required=True,
        translate=False)
    extension = fields.Selection([
            ('', ''),
            ('bib', 'BibTex'),
            ('bmp', 'Windows Bitmap'),
            ('csv', 'Text CSV'),
            ('dbf', 'dBase'),
            ('dif', 'Data Interchange Format'),
            ('doc', 'Microsoft Word 97/2000/XP'),
            ('doc6', 'Microsoft Word 6.0'),
            ('doc95', 'Microsoft Word 95'),
            ('docbook', 'DocBook'),
            ('emf', 'Enhanced Metafile'),
            ('eps', 'Encapsulated PostScript'),
            ('gif', 'Graphics Interchange Format'),
            ('html', 'HTML Document'),
            ('jpg', 'Joint Photographic Experts Group'),
            ('met', 'OS/2 Metafile'),
            ('ooxml', 'Microsoft Office Open XML'),
            ('pbm', 'Portable Bitmap'),
            ('pct', 'Mac Pict'),
            ('pdb', 'AportisDoc (Palm)'),
            ('pdf', 'Portable Document Format'),
            ('pgm', 'Portable Graymap'),
            ('png', 'Portable Network Graphic'),
            ('ppm', 'Portable Pixelmap'),
            ('ppt', 'Microsoft PowerPoint 97/2000/XP'),
            ('psw', 'Pocket Word'),
            ('pwp', 'PlaceWare'),
            ('pxl', 'Pocket Excel'),
            ('ras', 'Sun Raster Image'),
            ('rtf', 'Rich Text Format'),
            ('latex', 'LaTeX 2e'),
            ('sda', 'StarDraw 5.0 (OpenOffice.org Impress)'),
            ('sdc', 'StarCalc 5.0'),
            ('sdc4', 'StarCalc 4.0'),
            ('sdc3', 'StarCalc 3.0'),
            ('sdd', 'StarImpress 5.0'),
            ('sdd3', 'StarDraw 3.0 (OpenOffice.org Impress)'),
            ('sdd4', 'StarImpress 4.0'),
            ('sdw', 'StarWriter 5.0'),
            ('sdw4', 'StarWriter 4.0'),
            ('sdw3', 'StarWriter 3.0'),
            ('slk', 'SYLK'),
            ('svg', 'Scalable Vector Graphics'),
            ('svm', 'StarView Metafile'),
            ('swf', 'Macromedia Flash (SWF)'),
            ('sxc', 'OpenOffice.org 1.0 Spreadsheet'),
            ('sxi', 'OpenOffice.org 1.0 Presentation'),
            ('sxd', 'OpenOffice.org 1.0 Drawing'),
            ('sxd3', 'StarDraw 3.0'),
            ('sxd5', 'StarDraw 5.0'),
            ('sxw', 'Open Office.org 1.0 Text Document'),
            ('text', 'Text Encoded'),
            ('tiff', 'Tagged Image File Format'),
            ('txt', 'Plain Text'),
            ('wmf', 'Windows Metafile'),
            ('xhtml', 'XHTML Document'),
            ('xls', 'Microsoft Excel 97/2000/XP'),
            ('xls5', 'Microsoft Excel 5.0'),
            ('xls95', 'Microsoft Excel 95'),
            ('xpm', 'X PixMap'),
            ], translate=False,
        string='Extension', help='Leave empty for the same as template, '
        'see unoconv documentation for compatible format')
    module = fields.Char('Module', readonly=True, select=True)
    email = fields.Char('Email',
        help='Python dictonary where keys define "to" "cc" "subject"\n'
        "Example: {'to': 'test@example.com', 'cc': 'user@example.com'}")
    pyson_email = fields.Function(fields.Char('PySON Email'), 'get_pyson')

    @classmethod
    def __setup__(cls):
        super(ActionReport, cls).__setup__()
        cls._error_messages.update({
                'invalid_email': 'Invalid email definition on report "%s".',
                })

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        super(ActionReport, cls).__register__(module_name)

        cursor = Transaction().cursor
        table = TableHandler(cursor, cls, module_name)
        action_report = cls.__table__()

        # Migration from 1.0 report_name_uniq has been removed
        table.drop_constraint('report_name_uniq')

        # Migration from 1.0 output_format (m2o) is now extension (selection)
        if table.column_exist('output_format'):
            outputformat = Table('ir_action_report_outputformat')
            cursor.execute(*action_report.join(
                    outputformat,
                    condition=action_report.output_format == outputformat.id)
                .select(action_report.id,
                    where=outputformat.format == 'pdf'))

            ids = [x[0] for x in cursor.fetchall()]
            cls.write(cls.browse(ids), {'extension': 'pdf'})
            ids = cls.search([('id', 'not in', ids)])
            cls.write(cls.browse(ids), {'extension': 'odt'})

            table.drop_column("output_format")
            TableHandler.dropTable(cursor, 'ir.action.report.outputformat',
                'ir_action_report_outputformat')

        # Migrate from 2.0 remove required on extension
        table.not_null_action('extension', action='remove')
        cursor.execute(*action_report.update(
                [action_report.extension],
                [''],
                where=action_report.extension == 'odt'))

        # Migration from 2.0 report_content_data renamed into
        # report_content_custom to remove base64 encoding
        if (table.column_exist('report_content_data')
                and table.column_exist('report_content_custom')):
            limit = cursor.IN_MAX
            cursor.execute(*action_report.select(
                    Count(action_report.id)))
            report_count, = cursor.fetchone()
            for offset in range(0, report_count, limit):
                cursor.execute(*action_report.select(
                        action_report.id, action_report.report_content_data,
                        order_by=action_report.id,
                        limit=limit, offset=offset))
                for report_id, report in cursor.fetchall():
                    if report:
                        report = fields.Binary.cast(
                            base64.decodestring(bytes(report)))
                        cursor.execute(*action_report.update(
                                [action_report.report_content_custom],
                                [report],
                                where=action_report.id == report_id))
            table.drop_column('report_content_data')

        # Migration from 3.4 remove report_name_module_uniq constraint
        table.drop_constraint('report_name_module_uniq')

    @staticmethod
    def default_type():
        return 'ir.action.report'

    @staticmethod
    def default_report_content():
        return None

    @staticmethod
    def default_direct_print():
        return False

    @staticmethod
    def default_template_extension():
        return 'odt'

    @staticmethod
    def default_extension():
        return ''

    @staticmethod
    def default_module():
        return Transaction().context.get('module') or ''

    @classmethod
    def validate(cls, reports):
        super(ActionReport, cls).validate(reports)
        cls.check_email(reports)

    @classmethod
    def check_email(cls, reports):
        "Check email"
        for report in reports:
            if report.email:
                try:
                    value = PYSONDecoder().decode(report.email)
                except Exception:
                    value = None
                if isinstance(value, dict):
                    inkeys = set(value)
                    if not inkeys <= EMAIL_REFKEYS:
                        cls.raise_user_error('invalid_email', (
                                report.rec_name,))
                else:
                    cls.raise_user_error('invalid_email', (report.rec_name,))

    @classmethod
    def get_report_content(cls, reports, name):
        contents = {}
        converter = fields.Binary.cast
        default = None
        format_ = Transaction().context.pop('%s.%s'
            % (cls.__name__, name), '')
        if format_ == 'size':
            converter = len
            default = 0
        for report in reports:
            data = getattr(report, name + '_custom')
            if not data and getattr(report, name[:-8]):
                try:
                    with file_open(
                            getattr(report, name[:-8]).replace('/', os.sep),
                            mode='rb') as fp:
                        data = fp.read()
                except Exception:
                    data = None
            contents[report.id] = converter(data) if data else default
        return contents

    @classmethod
    def set_report_content(cls, records, name, value):
        cls.write(records, {'%s_custom' % name: value})

    def on_change_with_report_content_name(self, name=None):
        if not self.name:
            return
        return ''.join([self.name, os.extsep, self.template_extension])

    @classmethod
    def get_pyson(cls, reports, name):
        pysons = {}
        field = name[6:]
        defaults = {
            'email': '{}',
            }
        for report in reports:
            pysons[report.id] = (getattr(report, field)
                or defaults.get(field, 'null'))
        return pysons

    @classmethod
    def copy(cls, reports, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('module', None)

        new_reports = []
        for report in reports:
            if report.report:
                default['report_content'] = None
            default['report_name'] = report.report_name
            new_reports.extend(super(ActionReport, cls).copy([report],
                    default=default))
        return new_reports

    @classmethod
    def write(cls, reports, values, *args):
        context = Transaction().context
        if 'module' in context:
            actions = iter((reports, values) + args)
            args = []
            for reports, values in zip(actions, actions):
                values = values.copy()
                values['module'] = context['module']
                args.extend((reports, values))
            reports, values = args[:2]
            args = args[2:]
        super(ActionReport, cls).write(reports, values, *args)


class ActionActWindow(ActionMixin, ModelSQL, ModelView):
    "Action act window"
    __name__ = 'ir.action.act_window'
    domain = fields.Char('Domain Value')
    context = fields.Char('Context Value')
    order = fields.Char('Order Value')
    res_model = fields.Char('Model')
    act_window_views = fields.One2Many('ir.action.act_window.view',
            'act_window', 'Views')
    views = fields.Function(fields.Binary('Views'), 'get_views')
    act_window_domains = fields.One2Many('ir.action.act_window.domain',
        'act_window', 'Domains')
    domains = fields.Function(fields.Binary('Domains'), 'get_domains')
    limit = fields.Integer('Limit', required=True,
            help='Default limit for the list view')
    action = fields.Many2One('ir.action', 'Action', required=True,
            ondelete='CASCADE')
    window_name = fields.Boolean('Window Name',
            help='Use the action name as window name')
    search_value = fields.Char('Search Criteria',
            help='Default search criteria for the list view')
    pyson_domain = fields.Function(fields.Char('PySON Domain'), 'get_pyson')
    pyson_context = fields.Function(fields.Char('PySON Context'),
            'get_pyson')
    pyson_order = fields.Function(fields.Char('PySON Order'), 'get_pyson')
    pyson_search_value = fields.Function(fields.Char(
        'PySON Search Criteria'), 'get_pyson')

    @classmethod
    def __setup__(cls):
        super(ActionActWindow, cls).__setup__()
        cls._error_messages.update({
                'invalid_views': ('Invalid view "%(view)s" for action '
                    '"%(action)s".'),
                'invalid_domain': ('Invalid domain or search criteria '
                    '"%(domain)s" on action "%(action)s".'),
                'invalid_context': ('Invalid context "%(context)s" on action '
                    '"%(action)s".'),
                })
        cls.__rpc__.update({
                'get': RPC(),
                })

    @classmethod
    def __register__(cls, module_name):
        cursor = Transaction().cursor
        TableHandler = backend.get('TableHandler')
        act_window = cls.__table__()
        super(ActionActWindow, cls).__register__(module_name)

        table = TableHandler(cursor, cls, module_name)

        # Migration from 2.0: new search_value format
        cursor.execute(*act_window.update(
                [act_window.search_value], ['[]'],
                where=act_window.search_value == '{}'))

        # Migration from 3.0: auto_refresh removed
        table.drop_column('auto_refresh')

    @staticmethod
    def default_type():
        return 'ir.action.act_window'

    @staticmethod
    def default_context():
        return '{}'

    @staticmethod
    def default_limit():
        return 0

    @staticmethod
    def default_window_name():
        return True

    @staticmethod
    def default_search_value():
        return '[]'

    @classmethod
    def validate(cls, actions):
        super(ActionActWindow, cls).validate(actions)
        cls.check_views(actions)
        cls.check_domain(actions)
        cls.check_context(actions)

    @classmethod
    def check_views(cls, actions):
        "Check views"
        for action in actions:
            if action.res_model:
                for act_window_view in action.act_window_views:
                    view = act_window_view.view
                    if view.model != action.res_model:
                        cls.raise_user_error('invalid_views', {
                                'view': view.rec_name,
                                'action': action.rec_name,
                                })
                    if view.type == 'board':
                        cls.raise_user_error('invalid_views', {
                                'view': view.rec_name,
                                'action': action.rec_name,
                                })
            else:
                for act_window_view in action.act_window_views:
                    view = act_window_view.view
                    if view.model:
                        cls.raise_user_error('invalid_views', {
                                'view': view.rec_name,
                                'action': action.rec_name,
                                })
                    if view.type != 'board':
                        cls.raise_user_error('invalid_views', {
                                'view': view.rec_name,
                                'action': action.rec_name,
                                })

    @classmethod
    def check_domain(cls, actions):
        "Check domain and search_value"
        for action in actions:
            for domain in (action.domain, action.search_value):
                if not domain:
                    continue
                try:
                    value = PYSONDecoder().decode(domain)
                except Exception:
                    cls.raise_user_error('invalid_domain', {
                            'domain': domain,
                            'action': action.rec_name,
                            })
                if isinstance(value, PYSON):
                    if not value.types() == set([list]):
                        cls.raise_user_error('invalid_domain', {
                                'domain': domain,
                                'action': action.rec_name,
                                })
                elif not isinstance(value, list):
                    cls.raise_user_error('invalid_domain', {
                            'domain': domain,
                            'action': action.rec_name,
                            })
                else:
                    try:
                        fields.domain_validate(value)
                    except Exception:
                        cls.raise_user_error('invalid_domain', {
                                'domain': domain,
                                'action': action.rec_name,
                                })

    @classmethod
    def check_context(cls, actions):
        "Check context"
        for action in actions:
            if action.context:
                try:
                    value = PYSONDecoder().decode(action.context)
                except Exception:
                    cls.raise_user_error('invalid_context', {
                            'context': action.context,
                            'action': action.rec_name,
                            })
                if isinstance(value, PYSON):
                    if not value.types() == set([dict]):
                        cls.raise_user_error('invalid_context', {
                                'context': action.context,
                                'action': action.rec_name,
                                })
                elif not isinstance(value, dict):
                    cls.raise_user_error('invalid_context', {
                            'context': action.context,
                            'action': action.rec_name,
                            })
                else:
                    try:
                        fields.context_validate(value)
                    except Exception:
                        cls.raise_user_error('invalid_context', {
                                'context': action.context,
                                'action': action.rec_name,
                                })

    def get_views(self, name):
        return [(view.view.id, view.view.type)
            for view in self.act_window_views]

    def get_domains(self, name):
        return [(domain.name, domain.domain or '[]')
            for domain in self.act_window_domains]

    @classmethod
    def get_pyson(cls, windows, name):
        pysons = {}
        field = name[6:]
        defaults = {
            'domain': '[]',
            'context': '{}',
            'search_value': '{}',
            }
        for window in windows:
            pysons[window.id] = (getattr(window, field)
                or defaults.get(field, 'null'))
        return pysons

    @classmethod
    def get(cls, xml_id):
        'Get values from XML id or id'
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        Action = pool.get('ir.action')
        if '.' in xml_id:
            action_id = ModelData.get_id(*xml_id.split('.'))
        else:
            action_id = int(xml_id)
        return Action.get_action_values(cls.__name__, [action_id])[0]


class ActionActWindowView(ModelSQL, ModelView):
    "Action act window view"
    __name__ = 'ir.action.act_window.view'
    _rec_name = 'view'
    sequence = fields.Integer('Sequence', required=True)
    view = fields.Many2One('ir.ui.view', 'View', required=True,
            ondelete='CASCADE')
    act_window = fields.Many2One('ir.action.act_window', 'Action',
            ondelete='CASCADE')
    active = fields.Boolean('Active', select=True)

    @classmethod
    def __setup__(cls):
        super(ActionActWindowView, cls).__setup__()
        cls._order.insert(0, ('sequence', 'ASC'))

    @staticmethod
    def default_active():
        return True

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        super(ActionActWindowView, cls).__register__(module_name)
        table = TableHandler(Transaction().cursor, cls, module_name)

        # Migration from 1.0 remove multi
        table.drop_column('multi')

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        windows = super(ActionActWindowView, cls).create(vlist)
        pool.get('ir.action.keyword')._get_keyword_cache.clear()
        return windows

    @classmethod
    def write(cls, windows, values, *args):
        pool = Pool()
        super(ActionActWindowView, cls).write(windows, values, *args)
        pool.get('ir.action.keyword')._get_keyword_cache.clear()

    @classmethod
    def delete(cls, windows):
        pool = Pool()
        super(ActionActWindowView, cls).delete(windows)
        pool.get('ir.action.keyword')._get_keyword_cache.clear()


class ActionActWindowDomain(ModelSQL, ModelView):
    "Action act window domain"
    __name__ = 'ir.action.act_window.domain'
    name = fields.Char('Name', translate=True)
    sequence = fields.Integer('Sequence', required=True)
    domain = fields.Char('Domain')
    act_window = fields.Many2One('ir.action.act_window', 'Action',
        select=True, required=True, ondelete='CASCADE')
    active = fields.Boolean('Active')

    @classmethod
    def __setup__(cls):
        super(ActionActWindowDomain, cls).__setup__()
        cls._order.insert(0, ('sequence', 'ASC'))
        cls._error_messages.update({
                'invalid_domain': ('Invalid domain or search criteria '
                    '"%(domain)s" on action "%(action)s".'),
                })

    @staticmethod
    def default_active():
        return True

    @classmethod
    def validate(cls, actions):
        super(ActionActWindowDomain, cls).validate(actions)
        cls.check_domain(actions)

    @classmethod
    def check_domain(cls, actions):
        for action in actions:
            if not action.domain:
                continue
            try:
                value = PYSONDecoder().decode(action.domain)
            except Exception:
                value = None
            if isinstance(value, PYSON):
                if not value.types() == set([list]):
                    value = None
            elif not isinstance(value, list):
                value = None
            else:
                try:
                    fields.domain_validate(value)
                except Exception:
                    value = None
            if value is None:
                cls.raise_user_error('invalid_domain', {
                        'domain': action.domain,
                        'action': action.rec_name,
                        })


class ActionWizard(ActionMixin, ModelSQL, ModelView):
    "Action wizard"
    __name__ = 'ir.action.wizard'
    _action_name = 'wiz_name'
    wiz_name = fields.Char('Wizard name', required=True)
    action = fields.Many2One('ir.action', 'Action', required=True,
            ondelete='CASCADE')
    model = fields.Char('Model')
    email = fields.Char('Email')
    window = fields.Boolean('Window', help='Run wizard in a new window')

    @staticmethod
    def default_type():
        return 'ir.action.wizard'


class ActionURL(ActionMixin, ModelSQL, ModelView):
    "Action URL"
    __name__ = 'ir.action.url'
    url = fields.Char('Action Url', required=True)
    action = fields.Many2One('ir.action', 'Action', required=True,
            ondelete='CASCADE')

    @staticmethod
    def default_type():
        return 'ir.action.url'
