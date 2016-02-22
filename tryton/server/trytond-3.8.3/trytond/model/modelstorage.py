# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

import datetime
import time
import csv
import warnings
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO

from decimal import Decimal
from itertools import islice, ifilter, chain, izip
from functools import reduce
from operator import itemgetter
from collections import defaultdict

from trytond.model import Model
from trytond.model import fields
from trytond.tools import reduce_domain, memoize, is_instance_method, \
    grouped_slice
from trytond.pyson import PYSONEncoder, PYSONDecoder, PYSON
from trytond.const import OPERATORS
from trytond.config import config
from trytond.transaction import Transaction
from trytond.pool import Pool
from trytond.cache import LRUDict, freeze
from trytond import backend
from trytond.rpc import RPC
from .modelview import ModelView
from .descriptors import dualmethod

__all__ = ['ModelStorage', 'EvalEnvironment']


def cache_size():
    return Transaction().context.get('_record_cache_size',
        config.getint('cache', 'record'))


class ModelStorage(Model):
    """
    Define a model with storage capability in Tryton.
    """

    create_uid = fields.Many2One('res.user', 'Create User', readonly=True)
    create_date = fields.Timestamp('Create Date', readonly=True)
    write_uid = fields.Many2One('res.user', 'Write User', readonly=True)
    write_date = fields.Timestamp('Write Date', readonly=True)
    rec_name = fields.Function(fields.Char('Name'), 'get_rec_name',
            searcher='search_rec_name')

    @classmethod
    def __setup__(cls):
        super(ModelStorage, cls).__setup__()
        if issubclass(cls, ModelView):
            cls.__rpc__.update({
                    'create': RPC(readonly=False,
                        result=lambda r: map(int, r)),
                    'read': RPC(),
                    'write': RPC(readonly=False,
                        instantiate=slice(0, None, 2)),
                    'delete': RPC(readonly=False, instantiate=0),
                    'copy': RPC(readonly=False, instantiate=0,
                        result=lambda r: map(int, r)),
                    'search': RPC(result=lambda r: map(int, r)),
                    'search_count': RPC(),
                    'search_read': RPC(),
                    'export_data': RPC(instantiate=0),
                    'import_data': RPC(readonly=False),
                    })
        cls._constraints = []

    @staticmethod
    def default_create_uid():
        "Default value for uid field."
        return int(Transaction().user)

    @staticmethod
    def default_create_date():
        "Default value for create_date field."
        return datetime.datetime.today()

    @classmethod
    def create(cls, vlist):
        '''
        Returns the list of created records.
        '''
        pool = Pool()
        ModelAccess = pool.get('ir.model.access')
        ModelFieldAccess = pool.get('ir.model.field.access')

        ModelAccess.check(cls.__name__, 'create')

        all_fields = list(set(chain(*(v.iterkeys() for v in vlist))))
        ModelFieldAccess.check(cls.__name__, all_fields, 'write')

        # Increase transaction counter
        Transaction().counter += 1

    @classmethod
    def trigger_create(cls, records):
        '''
        Trigger create actions
        '''
        Trigger = Pool().get('ir.trigger')
        triggers = Trigger.get_triggers(cls.__name__, 'create')
        if not triggers:
            return
        for trigger in triggers:
            triggers = []
            for record in records:
                if Trigger.eval(trigger, record):
                    triggers.append(record)
            if triggers:
                Trigger.trigger_action(triggers, trigger)

    @classmethod
    def read(cls, ids, fields_names=None):
        '''
        Read fields_names of record ids.
        If fields_names is None, it read all fields.
        The order is not guaranteed.
        '''
        pool = Pool()
        ModelAccess = pool.get('ir.model.access')
        ModelFieldAccess = pool.get('ir.model.field.access')

        if not fields_names:
            fields_names = []
            for field_name in cls._fields.keys():
                if ModelAccess.check_relation(cls.__name__, field_name,
                        mode='read'):
                    fields_names.append(field_name)

        ModelAccess.check(cls.__name__, 'read')
        ModelFieldAccess.check(cls.__name__, fields_names, 'read')
        return []

    @classmethod
    def write(cls, records, values, *args):
        '''
        Write values on records.
        '''
        pool = Pool()
        ModelAccess = pool.get('ir.model.access')
        ModelFieldAccess = pool.get('ir.model.field.access')

        assert not len(args) % 2
        actions = iter((records, values) + args)
        all_records = []
        all_fields = set()
        for records, values in zip(actions, actions):
            if not cls.check_xml_record(records, values):
                cls.raise_user_error('write_xml_record',
                        error_description='xml_record_desc')
            all_records += records
            all_fields.update(values.iterkeys())

        ModelAccess.check(cls.__name__, 'write')
        ModelFieldAccess.check(cls.__name__, all_fields, 'write')

        # Increase transaction counter
        Transaction().counter += 1

        # Clean local cache
        for record in all_records:
            local_cache = record._local_cache.get(record.id)
            if local_cache:
                local_cache.clear()

        # Clean cursor cache
        for cache in Transaction().cursor.cache.itervalues():
            if cls.__name__ in cache:
                for record in all_records:
                    if record.id in cache[cls.__name__]:
                        cache[cls.__name__][record.id].clear()

    @classmethod
    def trigger_write_get_eligibles(cls, records):
        '''
        Return eligible records for write actions by triggers
        '''
        Trigger = Pool().get('ir.trigger')
        triggers = Trigger.get_triggers(cls.__name__, 'write')
        if not triggers:
            return {}
        eligibles = {}
        for trigger in triggers:
            eligibles[trigger] = []
            for record in records:
                if not Trigger.eval(trigger, record):
                    eligibles[trigger].append(record)
        return eligibles

    @classmethod
    def trigger_write(cls, eligibles):
        '''
        Trigger write actions.
        eligibles is a dictionary of the lists of eligible records by triggers
        '''
        Trigger = Pool().get('ir.trigger')
        for trigger, records in eligibles.iteritems():
            triggered = []
            for record in records:
                if Trigger.eval(trigger, record):
                    triggered.append(record)
            if triggered:
                Trigger.trigger_action(triggered, trigger)

    @classmethod
    def delete(cls, records):
        '''
        Delete records.
        '''
        ModelAccess = Pool().get('ir.model.access')

        ModelAccess.check(cls.__name__, 'delete')
        if not cls.check_xml_record(records, None):
            cls.raise_user_error('delete_xml_record',
                    error_description='xml_record_desc')

        # Increase transaction counter
        Transaction().counter += 1

        # Clean cursor cache
        for cache in Transaction().cursor.cache.values():
            for cache in (cache, cache.get('_language_cache', {}).values()):
                if cls.__name__ in cache:
                    for record in records:
                        if record.id in cache[cls.__name__]:
                            del cache[cls.__name__][record.id]

    @classmethod
    def trigger_delete(cls, records):
        '''
        Trigger delete actions
        '''
        Trigger = Pool().get('ir.trigger')
        triggers = Trigger.get_triggers(cls.__name__, 'delete')
        if not triggers:
            return
        for trigger in triggers:
            triggered = []
            for record in records:
                if Trigger.eval(trigger, record):
                    triggered.append(record)
            if triggered:
                Trigger.trigger_action(triggered, trigger)

    @classmethod
    def copy(cls, records, default=None):
        '''
        Duplicate the records and return a list of new records.
        '''
        pool = Pool()
        Lang = pool.get('ir.lang')
        if default is None:
            default = {}

        if 'state' not in default:
            if 'state' in cls._defaults:
                default['state'] = cls._defaults['state']()

        def convert_data(field_defs, data):
            data = data.copy()
            for field_name in field_defs:
                ftype = field_defs[field_name]['type']

                if field_name in (
                        'create_date',
                        'create_uid',
                        'write_date',
                        'write_uid',
                        ):
                    del data[field_name]

                if field_name in default:
                    data[field_name] = default[field_name]
                elif (isinstance(cls._fields[field_name], fields.Function)
                        and not isinstance(cls._fields[field_name],
                            fields.Property)):
                    del data[field_name]
                elif ftype in ('many2one', 'one2one'):
                    try:
                        data[field_name] = data[field_name] and \
                            data[field_name][0]
                    except Exception:
                        pass
                elif ftype in ('one2many',):
                    if data[field_name]:
                        data[field_name] = [('copy', data[field_name])]
                elif ftype == 'many2many':
                    if data[field_name]:
                        data[field_name] = [('add', data[field_name])]
            if 'id' in data:
                del data['id']
            return data

        # Reset MPTT field to the default value
        mptt = set()
        for field in cls._fields.itervalues():
            if (isinstance(field, fields.Many2One)
                    and field.model_name == cls.__name__
                    and field.left and field.right):
                mptt.add(field.left)
                mptt.add(field.right)
        fields_names = [n for n, f in cls._fields.iteritems()
            if (not isinstance(f, fields.Function)
                or isinstance(f, fields.Property))
            and n not in mptt]
        ids = map(int, records)
        datas = cls.read(ids, fields_names=fields_names)
        datas = dict((d['id'], d) for d in datas)
        field_defs = cls.fields_get(fields_names=fields_names)
        to_create = []
        for id in ids:
            data = convert_data(field_defs, datas[id])
            to_create.append(data)
        new_records = cls.create(to_create)
        new_ids = dict(izip(ids, map(int, new_records)))

        fields_translate = {}
        for field_name, field in field_defs.iteritems():
            if field_name in cls._fields and \
                    getattr(cls._fields[field_name], 'translate', False):
                fields_translate[field_name] = field

        if fields_translate:
            langs = Lang.search([
                ('translatable', '=', True),
                ])
            if langs:
                for lang in langs:
                    # Prevent fuzzing translations when copying as the terms
                    # should be the same.
                    with Transaction().set_context(language=lang.code,
                            fuzzy_translation=False):
                        datas = cls.read(ids,
                                fields_names=fields_translate.keys() + ['id'])
                        for data in datas:
                            data_id = data['id']
                            data = convert_data(fields_translate, data)
                            cls.write([cls(new_ids[data_id])], data)
        return cls.browse(new_ids.values())

    @classmethod
    def search(cls, domain, offset=0, limit=None, order=None, count=False):
        '''
        Return a list of records that match the domain.
        '''
        if count:
            return 0
        return []

    @classmethod
    def search_count(cls, domain):
        '''
        Return the number of records that match the domain.
        '''
        res = cls.search(domain, count=True)
        if isinstance(res, list):
            return len(res)
        return res

    @classmethod
    def search_read(cls, domain, offset=0, limit=None, order=None,
            fields_names=None):
        '''
        Call search and read functions at once.
        Useful for the client to reduce the number of calls.
        '''
        records = cls.search(domain, offset=offset, limit=limit, order=order)

        if not fields_names:
            fields_names = cls._fields.keys()
        if 'id' not in fields_names:
            fields_names.append('id')
        rows = cls.read(map(int, records), fields_names)
        index = {r.id: i for i, r in enumerate(records)}
        rows.sort(key=lambda r: index[r['id']])
        return rows

    @classmethod
    def _search_domain_active(cls, domain, active_test=True):
        # reduce_domain return a new instance so we can safety modify domain
        domain = reduce_domain(domain)
        # if the object has a field named 'active', filter out all inactive
        # records unless they were explicitely asked for
        if not ('active' in cls._fields
                and active_test
                and Transaction().context.get('active_test', True)):
            return domain

        def process(domain):
            i = 0
            active_found = False
            while i < len(domain):
                arg = domain[i]
                # add test for xmlrpc that doesn't handle tuple
                if (isinstance(arg, tuple)
                        or (isinstance(arg, list)
                            and len(arg) > 2
                            and arg[1] in OPERATORS)):
                    if arg[0] == 'active':
                        active_found = True
                elif isinstance(arg, list):
                    domain[i] = process(domain[i])
                i += 1
            if not active_found:
                if (domain and ((isinstance(domain[0], basestring)
                                and domain[0] == 'AND')
                            or (not isinstance(domain[0], basestring)))):
                    domain.append(('active', '=', True))
                else:
                    domain = ['AND', domain, ('active', '=', True)]
            return domain
        return process(domain)

    def get_rec_name(self, name):
        '''
        Return the rec_name of the instance.
        It is used by the Function field rec_name.
        '''
        rec_name = self._rec_name
        if rec_name not in self._fields:
            rec_name = 'id'
        return unicode(getattr(self, rec_name))

    @classmethod
    def search_rec_name(cls, name, clause):
        '''
        Return a list of arguments for search on rec_name.
        '''
        rec_name = cls._rec_name
        if rec_name not in cls._fields:
            return []
        return [(rec_name,) + tuple(clause[1:])]

    @classmethod
    def search_global(cls, text):
        '''
        Yield tuples (record, name, icon) for text
        '''
        # TODO improve search clause
        for record in cls.search([
                    ('rec_name', 'ilike', '%%%s%%' % text),
                    ]):
            yield record, record.rec_name, None

    @classmethod
    def browse(cls, ids):
        '''
        Return a list of instance for the ids
        '''
        ids = map(int, ids)
        local_cache = LRUDict(cache_size())
        return [cls(int(x), _ids=ids, _local_cache=local_cache) for x in ids]

    @staticmethod
    def __export_row(record, fields_names):
        pool = Pool()
        lines = []
        data = ['' for x in range(len(fields_names))]
        done = []
        for fpos in range(len(fields_names)):
            fields_tree = fields_names[fpos]
            if not fields_tree:
                continue
            value = record
            i = 0
            while i < len(fields_tree):
                if not isinstance(value, ModelStorage):
                    break
                field_name = fields_tree[i]
                descriptor = None
                if '.' in field_name:
                    field_name, descriptor = field_name.split('.')
                eModel = pool.get(value.__name__)
                field = eModel._fields[field_name]
                if field.states and 'invisible' in field.states:
                    pyson_invisible = PYSONEncoder().encode(
                            field.states['invisible'])
                    env = EvalEnvironment(value, eModel)
                    env.update(Transaction().context)
                    env['current_date'] = datetime.datetime.today()
                    env['time'] = time
                    env['context'] = Transaction().context
                    env['active_id'] = value.id
                    invisible = PYSONDecoder(env).decode(pyson_invisible)
                    if invisible:
                        value = ''
                        break
                if descriptor:
                    value = getattr(field, descriptor)().__get__(value, eModel)
                else:
                    value = getattr(value, field_name)
                if isinstance(value, (list, tuple)):
                    first = True
                    child_fields_names = [(x[:i + 1] == fields_tree[:i + 1] and
                        x[i + 1:]) or [] for x in fields_names]
                    if child_fields_names in done:
                        break
                    done.append(child_fields_names)
                    for child_record in value:
                        child_lines = ModelStorage.__export_row(child_record,
                                child_fields_names)
                        if first:
                            for child_fpos in xrange(len(fields_names)):
                                if child_lines and child_lines[0][child_fpos]:
                                    data[child_fpos] = \
                                        child_lines[0][child_fpos]
                            lines += child_lines[1:]
                            first = False
                        else:
                            lines += child_lines
                    break
                i += 1
            if i == len(fields_tree):
                if value is None:
                    value = ''
                elif isinstance(value, Model):
                    value = str(value)
                data[fpos] = value
        return [data] + lines

    @classmethod
    def export_data(cls, records, fields_names):
        '''
        Return list of list of values for each record.
        The list of values follows fields_names.
        Relational fields are defined with '/' at any depth.
        '''
        fields_names = [x.split('/') for x in fields_names]
        data = []
        for record in records:
            data += cls.__export_row(record, fields_names)
        return data

    @classmethod
    def import_data(cls, fields_names, data):
        '''
        Create records for all values in data.
        The field names of values must be defined in fields_names.
        '''
        pool = Pool()

        @memoize(1000)
        def get_many2one(relation, value):
            if not value:
                return None
            Relation = pool.get(relation)
            res = Relation.search([
                ('rec_name', '=', value),
                ], limit=2)
            if len(res) < 1:
                cls.raise_user_error('relation_not_found', (value, relation))
            elif len(res) > 1:
                cls.raise_user_error('too_many_relations_found',
                    (value, relation))
            else:
                res = res[0].id
            return res

        @memoize(1000)
        def get_many2many(relation, value):
            if not value:
                return None
            res = []
            Relation = pool.get(relation)
            for word in csv.reader(StringIO.StringIO(value), delimiter=',',
                    quoting=csv.QUOTE_NONE, escapechar='\\').next():
                res2 = Relation.search([
                    ('rec_name', '=', word),
                    ], limit=2)
                if len(res2) < 1:
                    cls.raise_user_error('relation_not_found',
                        (word, relation))
                elif len(res2) > 1:
                    cls.raise_user_error('too_many_relations_found',
                        (word, relation))
                else:
                    res.extend(res2)
            if len(res):
                res = [('add', [x.id for x in res])]
            return res

        def get_one2one(relation, value):
            return ('add', get_many2one(relation, value))

        @memoize(1000)
        def get_reference(value, field):
            if not value:
                return None
            try:
                relation, value = value.split(',', 1)
            except Exception:
                cls.raise_user_error('reference_syntax_error',
                    (value, '/'.join(field)))
            Relation = pool.get(relation)
            res = Relation.search([
                ('rec_name', '=', value),
                ], limit=2)
            if len(res) < 1:
                cls.raise_user_error('relation_not_found', (value, relation))
            elif len(res) > 1:
                cls.raise_user_error('too_many_relations_found',
                    (value, relation))
            else:
                res = '%s,%s' % (relation, res[0].id)
            return res

        @memoize(1000)
        def get_by_id(value, field):
            if not value:
                return None
            relation = None
            ftype = fields_def[field[-1][:-3]]['type']
            if ftype == 'many2many':
                value = csv.reader(StringIO.StringIO(value), delimiter=',',
                        quoting=csv.QUOTE_NONE, escapechar='\\').next()
            elif ftype == 'reference':
                try:
                    relation, value = value.split(',', 1)
                except Exception:
                    cls.raise_user_error('reference_syntax_error',
                        (value, '/'.join(field)))
                value = [value]
            else:
                value = [value]
            res_ids = []
            for word in value:
                try:
                    module, xml_id = word.rsplit('.', 1)
                except Exception:
                    cls.raise_user_error('xml_id_syntax_error',
                        (word, '/'.join(field)))
                db_id = ModelData.get_id(module, xml_id)
                res_ids.append(db_id)
            if ftype == 'many2many' and res_ids:
                return [('add', res_ids)]
            elif ftype == 'reference' and res_ids:
                return '%s,%s' % (relation, str(res_ids[0]))
            return res_ids and res_ids[0] or False

        def process_lines(data, prefix, fields_def, position=0):
            line = data[position]
            row = {}
            translate = {}
            todo = set()
            prefix_len = len(prefix)
            # Import normal fields_names
            for i, field in enumerate(fields_names):
                if i >= len(line):
                    raise Exception('ImportError',
                        'Please check that all your lines have %d cols.'
                        % len(fields_names))
                is_prefix_len = (len(field) == (prefix_len + 1))
                value = line[i]
                if is_prefix_len and field[-1].endswith(':id'):
                    row[field[0][:-3]] = get_by_id(value, field)
                elif is_prefix_len and ':lang=' in field[-1]:
                    field_name, lang = field[-1].split(':lang=')
                    translate.setdefault(lang, {})[field_name] = value or False
                elif is_prefix_len and prefix == field[:-1]:
                    this_field_def = fields_def[field[-1]]
                    field_type = this_field_def['type']
                    res = None
                    if field_type == 'boolean':
                        if value.lower() == 'true':
                            res = True
                        elif value.lower() == 'false':
                            res = False
                        elif not value:
                            res = False
                        else:
                            res = bool(int(value))
                    elif field_type == 'integer':
                        res = int(value) if value else None
                    elif field_type == 'float':
                        res = float(value) if value else None
                    elif field_type == 'numeric':
                        res = Decimal(value) if value else None
                    elif field_type == 'date':
                        res = (datetime.datetime.strptime(value,
                                '%Y-%m-%d').date()
                            if value else None)
                    elif field_type == 'datetime':
                        res = (datetime.datetime.strptime(value,
                                '%Y-%m-%d %H:%M:%S')
                            if value else None)
                    elif field_type == 'many2one':
                        res = get_many2one(this_field_def['relation'], value)
                    elif field_type == 'many2many':
                        res = get_many2many(this_field_def['relation'], value)
                    elif field_type == 'one2one':
                        res = get_one2one(this_field_def['relation'], value)
                    elif field_type == 'reference':
                        res = get_reference(value, field)
                    else:
                        res = value or None
                    row[field[-1]] = res
                elif prefix == field[0:prefix_len]:
                    todo.add(field[prefix_len])
            # Import one2many fields
            nbrmax = 1
            for field in todo:
                newfd = pool.get(fields_def[field]['relation']
                        ).fields_get()
                res = process_lines(data, prefix + [field], newfd,
                        position)
                (newrow, max2, _) = res
                nbrmax = max(nbrmax, max2)
                reduce(lambda x, y: x and y, newrow)
                row[field] = (reduce(lambda x, y: x or y, newrow.values()) and
                         [('create', [newrow])]) or []
                i = max2
                while (position + i) < len(data):
                    test = True
                    for j, field2 in enumerate(fields_names):
                        if (len(field2) <= (prefix_len + 1)
                                and data[position + i][j]):
                            test = False
                            break
                    if not test:
                        break
                    (newrow, max2, _) = \
                        process_lines(data, prefix + [field], newfd,
                            position + i)
                    if reduce(lambda x, y: x or y, newrow.values()):
                        row[field].append(('create', [newrow]))
                    i += max2
                    nbrmax = max(nbrmax, i)
            if prefix_len == 0:
                for i in xrange(max(nbrmax, 1)):
                    data.pop(0)
            return (row, nbrmax, translate)

        ModelData = pool.get('ir.model.data')

        len_fields_names = len(fields_names)
        assert all(len(x) == len_fields_names for x in data)
        fields_names = [x.split('/') for x in fields_names]
        fields_def = cls.fields_get()

        to_create, translations, languages = [], [], set()
        while len(data):
            (res, _, translate) = \
                process_lines(data, [], fields_def)
            to_create.append(res)
            translations.append(translate)
            languages.update(translate)
        new_records = cls.create(to_create)
        for language in languages:
            translated = [t.get(language, {}) for t in translations]
            with Transaction().set_context(language=language):
                cls.write(*chain(*ifilter(itemgetter(1),
                            izip(([r] for r in new_records), translated))))
        return len(new_records)

    @classmethod
    def check_xml_record(cls, records, values):
        """
        Check if a list of records and their corresponding fields are
        originating from xml data. This is used by write and delete
        functions: if the return value is True the records can be
        written/deleted, False otherwise. The default behaviour is to
        forbid any modification on records/fields originating from
        xml. Values is the dictionary of written values. If values is
        equal to None, no field by field check is performed, False is
        returned as soon as one of the record comes from the xml.
        """
        ModelData = Pool().get('ir.model.data')
        # Allow root user to update/delete
        if Transaction().user == 0:
            return True
        with Transaction().set_context(_check_access=False):
            models_data = ModelData.search([
                ('model', '=', cls.__name__),
                ('db_id', 'in', map(int, records)),
                ])
            if not models_data:
                return True
            if values is None:
                return False
            for model_data in models_data:
                if not model_data.values:
                    continue
                xml_values = ModelData.load_values(model_data.values)
                for key, val in values.iteritems():
                    if key in xml_values and val != xml_values[key]:
                        return False
        return True

    @classmethod
    def check_recursion(cls, records, parent='parent', rec_name='rec_name'):
        '''
        Function that checks if there is no recursion in the tree
        composed with parent as parent field name.
        '''
        parent_type = cls._fields[parent]._type

        if parent_type not in ('many2one', 'many2many', 'one2one'):
            raise Exception(
                'Unsupported field type "%s" for field "%s" on "%s"'
                % (parent_type, parent, cls.__name__))

        visited = set()

        for record in records:
            walked = set()
            walker = getattr(record, parent)
            while walker:
                if parent_type == 'many2many':
                    for walk in walker:
                        walked.add(walk.id)
                        if walk.id == record.id:
                            parent_rec_name = ', '.join(getattr(r, rec_name)
                                for r in getattr(record, parent))
                            cls.raise_user_error('recursion_error', {
                                    'rec_name': getattr(record, rec_name),
                                    'parent_rec_name': parent_rec_name,
                                    })
                    walker = list(chain(*(getattr(walk, parent)
                                for walk in walker if walk.id not in visited)))
                else:
                    walked.add(walker.id)
                    if walker.id == record.id:
                        cls.raise_user_error('recursion_error', {
                                'rec_name': getattr(record, rec_name),
                                'parent_rec_name': getattr(getattr(record,
                                        parent), rec_name)
                                })
                    walker = (getattr(walker, parent) not in visited
                        and getattr(walker, parent))
            visited.update(walked)

    @classmethod
    def _get_error_args(cls, field_name):
        pool = Pool()
        ModelField = pool.get('ir.model.field')
        error_args = {
            'field': field_name,
            'model': cls.__name__
            }
        if ModelField:
            model_fields = ModelField.search([
                        ('name', '=', field_name),
                        ('model.model', '=', cls.__name__),
                        ], limit=1)
            if model_fields:
                model_field, = model_fields
                error_args.update({
                        'field': model_field.field_description,
                        'model': model_field.model.name,
                        })
        return error_args

    @classmethod
    def validate(cls, records):
        pass

    @classmethod
    def _validate(cls, records, field_names=None):
        pool = Pool()
        # Ensure that records are readable
        with Transaction().set_context(_check_access=False):
            records = cls.browse(records)

        def call(name):
            method = getattr(cls, name)
            if not is_instance_method(cls, name):
                return method(records)
            else:
                return all(method(r) for r in records)
        for field in cls._constraints:
            warnings.warn(
                '_constraints is deprecated, override validate instead',
                DeprecationWarning, stacklevel=2)
            if not call(field[0]):
                cls.raise_user_error(field[1])

        ctx_pref = {}
        if Transaction().user:
            try:
                User = pool.get('res.user')
            except KeyError:
                pass
            else:
                ctx_pref = User.get_preferences(context_only=True)

        def is_pyson(test):
            if isinstance(test, PYSON):
                return True
            if isinstance(test, (list, tuple)):
                for i in test:
                    if isinstance(i, PYSON):
                        return True
                    if isinstance(i, (list, tuple)):
                        if is_pyson(i):
                            return True
            if isinstance(test, dict):
                for key, value in test.items():
                    if isinstance(value, PYSON):
                        return True
                    if isinstance(value, (list, tuple, dict)):
                        if is_pyson(value):
                            return True
            return False

        def validate_domain(field):
            if not field.domain:
                return
            if field._type in ['dict', 'reference']:
                return
            if field._type in ('many2one', 'one2many'):
                Relation = pool.get(field.model_name)
            elif field._type in ('many2many', 'one2one'):
                Relation = field.get_target()
            else:
                Relation = cls
            domains = defaultdict(list)
            if is_pyson(field.domain):
                pyson_domain = PYSONEncoder().encode(field.domain)
                for record in records:
                    env = EvalEnvironment(record, cls)
                    env.update(Transaction().context)
                    env['current_date'] = datetime.datetime.today()
                    env['time'] = time
                    env['context'] = Transaction().context
                    env['active_id'] = record.id
                    domain = freeze(PYSONDecoder(env).decode(pyson_domain))
                    domains[domain].append(record)
            else:
                domains[freeze(field.domain)].extend(records)

            for domain, sub_records in domains.iteritems():
                validate_relation_domain(field, sub_records, Relation, domain)

        def validate_relation_domain(field, records, Relation, domain):
            if field._type in ('many2one', 'one2many', 'many2many', 'one2one'):
                relations = set()
                for record in records:
                    if getattr(record, field.name):
                        if field._type in ('many2one', 'one2one'):
                            relations.add(getattr(record, field.name))
                        else:
                            relations.update(getattr(record, field.name))
            else:
                # Cache alignment is not a problem
                relations = set(records)
            if relations:
                for sub_relations in grouped_slice(relations):
                    sub_relations = set(sub_relations)
                    finds = Relation.search(['AND',
                            [('id', 'in', [r.id for r in sub_relations])],
                            domain,
                            ])
                    if sub_relations != set(finds):
                        cls.raise_user_error('domain_validation_record',
                            error_args=cls._get_error_args(field.name))

        field_names = set(field_names or [])
        function_fields = {name for name, field in cls._fields.iteritems()
            if isinstance(field, fields.Function)}
        ctx_pref['active_test'] = False
        with Transaction().set_context(ctx_pref):
            for field_name, field in cls._fields.iteritems():
                depends = set(field.depends)
                if (field_names
                        and field_name not in field_names
                        and not (depends & field_names)
                        and not (depends & function_fields)):
                    continue
                if isinstance(field, fields.Function) and \
                        not field.setter:
                    continue

                validate_domain(field)

                def required_test(value, field_name):
                    if (isinstance(value, (type(None), type(False), list,
                                    tuple, basestring, dict))
                            and not value):
                        cls.raise_user_error('required_validation_record',
                            error_args=cls._get_error_args(field_name))
                # validate states required
                if field.states and 'required' in field.states:
                    if is_pyson(field.states['required']):
                        pyson_required = PYSONEncoder().encode(
                                field.states['required'])
                        for record in records:
                            env = EvalEnvironment(record, cls)
                            env.update(Transaction().context)
                            env['current_date'] = datetime.datetime.today()
                            env['time'] = time
                            env['context'] = Transaction().context
                            env['active_id'] = record.id
                            required = PYSONDecoder(env).decode(pyson_required)
                            if required:
                                required_test(getattr(record, field_name),
                                    field_name)
                    else:
                        if field.states['required']:
                            for record in records:
                                required_test(getattr(record, field_name),
                                    field_name)
                # validate required
                if field.required:
                    for record in records:
                        required_test(getattr(record, field_name), field_name)
                # validate size
                if hasattr(field, 'size') and field.size is not None:
                    for record in records:
                        if isinstance(field.size, PYSON):
                            pyson_size = PYSONEncoder().encode(field.size)
                            env = EvalEnvironment(record, cls)
                            env.update(Transaction().context)
                            env['current_date'] = datetime.datetime.today()
                            env['time'] = time
                            env['context'] = Transaction().context
                            env['active_id'] = record.id
                            field_size = PYSONDecoder(env).decode(pyson_size)
                        else:
                            field_size = field.size
                        size = len(getattr(record, field_name) or '')
                        if (size > field_size >= 0):
                            error_args = cls._get_error_args(field_name)
                            error_args['size'] = size
                            cls.raise_user_error('size_validation_record',
                                error_args=error_args)

                def digits_test(value, digits, field_name):
                    def raise_user_error(value):
                        error_args = cls._get_error_args(field_name)
                        error_args['digits'] = digits[1]
                        error_args['value'] = repr(value)
                        cls.raise_user_error('digits_validation_record',
                            error_args=error_args)
                    if value is None:
                        return
                    if isinstance(value, Decimal):
                        if (value.quantize(Decimal(str(10.0 ** -digits[1])))
                                != value):
                            raise_user_error(value)
                    elif backend.name() != 'mysql':
                        if not (round(value, digits[1]) == float(value)):
                            raise_user_error(value)
                # validate digits
                if hasattr(field, 'digits') and field.digits:
                    if is_pyson(field.digits):
                        pyson_digits = PYSONEncoder().encode(field.digits)
                        for record in records:
                            env = EvalEnvironment(record, cls)
                            env.update(Transaction().context)
                            env['current_date'] = datetime.datetime.today()
                            env['time'] = time
                            env['context'] = Transaction().context
                            env['active_id'] = record.id
                            digits = PYSONDecoder(env).decode(pyson_digits)
                            digits_test(getattr(record, field_name), digits,
                                field_name)
                    else:
                        for record in records:
                            digits_test(getattr(record, field_name),
                                field.digits, field_name)

                # validate selection
                if hasattr(field, 'selection') and field.selection:
                    if isinstance(field.selection, (tuple, list)):
                        test = set(dict(field.selection).keys())
                    for record in records:
                        value = getattr(record, field_name)
                        if field._type == 'reference':
                            if isinstance(value, ModelStorage):
                                value = value.__class__.__name__
                            elif value:
                                value, _ = value.split(',')
                        if not isinstance(field.selection, (tuple, list)):
                            sel_func = getattr(cls, field.selection)
                            if not is_instance_method(cls, field.selection):
                                test = sel_func()
                            else:
                                test = sel_func(record)
                            test = set(dict(test))
                        # None and '' are equivalent
                        if '' in test or None in test:
                            test.add('')
                            test.add(None)
                        if value not in test:
                            error_args = cls._get_error_args(field_name)
                            error_args['value'] = value
                            cls.raise_user_error('selection_validation_record',
                                error_args=error_args)

                def format_test(value, format, field_name):
                    if not value:
                        return
                    if not isinstance(value, datetime.time):
                        value = value.time()
                    if value != datetime.datetime.strptime(
                            value.strftime(format), format).time():
                        error_args = cls._get_error_args(field_name)
                        error_args['value'] = value
                        cls.raise_user_error('time_format_validation_record',
                            error_args=error_args)

                # validate time format
                if (field._type in ('datetime', 'time')
                        and field_name not in ('create_date', 'write_date')):
                    if is_pyson(field.format):
                        pyson_format = PYSONDecoder().encode(field.format)
                        for record in records:
                            env = EvalEnvironment(record, cls)
                            env.update(Transaction().context)
                            env['current_date'] = datetime.datetime.today()
                            env['time'] = time
                            env['context'] = Transaction().context
                            env['active_id'] = record.id
                            format = PYSONDecoder(env).decode(pyson_format)
                            format_test(getattr(record, field_name), format,
                                field_name)
                    else:
                        for record in records:
                            format_test(getattr(record, field_name),
                                field.format, field_name)

        for record in records:
            record.pre_validate()

        cls.validate(records)

    @classmethod
    def _clean_defaults(cls, defaults):
        pool = Pool()
        vals = {}
        for field in defaults.keys():
            fld_def = cls._fields[field]
            if fld_def._type in ('many2one', 'one2one'):
                if isinstance(defaults[field], (list, tuple)):
                    vals[field] = defaults[field][0]
                else:
                    vals[field] = defaults[field]
            elif fld_def._type in ('one2many',):
                obj = pool.get(fld_def.model_name)
                vals[field] = []
                for defaults2 in defaults[field]:
                    vals2 = obj._clean_defaults(defaults2)
                    vals[field].append(('create', [vals2]))
            elif fld_def._type in ('many2many',):
                vals[field] = [('add', defaults[field])]
            elif fld_def._type in ('boolean',):
                vals[field] = bool(defaults[field])
            else:
                vals[field] = defaults[field]
        return vals

    def __init__(self, id=None, **kwargs):
        _ids = kwargs.pop('_ids', None)
        _local_cache = kwargs.pop('_local_cache', None)
        self._cursor = Transaction().cursor
        self._user = Transaction().user
        self._context = Transaction().context
        if id is not None:
            id = int(id)
        if _ids is not None:
            self._ids = _ids
            assert id in _ids
        else:
            self._ids = [id]

        self._cursor_cache = self._cursor.get_cache()

        if _local_cache is not None:
            self._local_cache = _local_cache
        else:
            self._local_cache = LRUDict(cache_size())
        self._local_cache.counter = Transaction().counter

        super(ModelStorage, self).__init__(id, **kwargs)

    @property
    def _cache(self):
        cache = self._cursor_cache
        if self.__name__ not in cache:
            cache[self.__name__] = LRUDict(cache_size())
        return cache[self.__name__]

    def __getattr__(self, name):
        try:
            return super(ModelStorage, self).__getattr__(name)
        except AttributeError:
            if self.id < 0:
                raise

        counter = Transaction().counter
        if self._local_cache.counter != counter:
            self._local_cache.clear()
            self._local_cache.counter = counter

        # fetch the definition of the field
        try:
            field = self._fields[name]
        except KeyError:
            raise AttributeError('"%s" has no attribute "%s"' % (self, name))

        try:
            return self._local_cache[self.id][name]
        except KeyError:
            pass
        try:
            if field._type not in ('many2one', 'reference'):
                return self._cache[self.id][name]
        except KeyError:
            pass

        # build the list of fields we will fetch
        ffields = {
            name: field,
            }
        if field.loading == 'eager':
            FieldAccess = Pool().get('ir.model.field.access')
            fread_accesses = {}
            fread_accesses.update(FieldAccess.check(self.__name__,
                self._fields.keys(), 'read', access=True))
            to_remove = set(x for x, y in fread_accesses.iteritems()
                    if not y and x != name)

            threshold = config.getint('cache', 'field')

            def not_cached(item):
                fname, field = item
                return (fname not in self._cache.get(self.id, {})
                    and fname not in self._local_cache.get(self.id, {}))

            def to_load(item):
                fname, field = item
                return (field.loading == 'eager'
                    and fname not in to_remove)

            def overrided(item):
                fname, field = item
                return fname in self._fields

            ifields = ifilter(to_load,
                ifilter(not_cached,
                    self._fields.iteritems()))
            ifields = islice(ifields, 0, threshold)
            ffields.update(ifields)

        # add datetime_field
        for field in ffields.values():
            if hasattr(field, 'datetime_field') and field.datetime_field:
                datetime_field = self._fields[field.datetime_field]
                ffields[field.datetime_field] = datetime_field

        # add depends of field with context
        for field in ffields.values():
            if field.context:
                eval_fields = fields.get_eval_fields(field.context)
                for context_field_name in eval_fields:
                    if context_field_name in field.depends:
                        continue
                    context_field = self._fields.get(context_field_name)
                    if context_field not in ffields:
                        ffields[context_field_name] = context_field

        def filter_(id_):
            return (name not in self._cache.get(id_, {})
                and name not in self._local_cache.get(id_, {}))

        def unique(ids):
            s = set()
            for id_ in ids:
                if id_ not in s:
                    s.add(id_)
                    yield id_
        index = self._ids.index(self.id)
        ids = chain(islice(self._ids, index, None),
            islice(self._ids, 0, max(index - 1, 0)))
        ids = islice(unique(ifilter(filter_, ids)), self._cursor.IN_MAX)

        def instantiate(field, value, data):
            if field._type in ('many2one', 'one2one', 'reference'):
                if value is None or value is False:
                    return None
            elif field._type in ('one2many', 'many2many'):
                if not value:
                    return ()
            try:
                if field._type == 'reference':
                    model_name, record_id = value.split(',')
                    Model = Pool().get(model_name)
                    try:
                        value = int(record_id)
                    except ValueError:
                        return value
                else:
                    Model = field.get_target()
            except KeyError:
                return value
            ctx = {}
            if field.context:
                pyson_context = PYSONEncoder().encode(field.context)
                ctx.update(PYSONDecoder(data).decode(pyson_context))
            datetime_ = None
            if getattr(field, 'datetime_field', None):
                datetime_ = data.get(field.datetime_field)
                ctx = {'_datetime': datetime_}
            with Transaction().set_context(**ctx):
                key = (Model, freeze(ctx))
                local_cache = model2cache.setdefault(key,
                    LRUDict(cache_size()))
                ids = model2ids.setdefault(key, [])
                if field._type in ('many2one', 'one2one', 'reference'):
                    ids.append(value)
                    return Model(value, _ids=ids, _local_cache=local_cache)
                elif field._type in ('one2many', 'many2many'):
                    ids.extend(value)
                    return tuple(Model(id, _ids=ids, _local_cache=local_cache)
                        for id in value)

        model2ids = {}
        model2cache = {}
        # Read the data
        with Transaction().set_cursor(self._cursor), \
                Transaction().set_user(self._user), \
                Transaction().set_context(self._context):
            if self.id in self._cache and name in self._cache[self.id]:
                # Use values from cache
                ids = islice(chain(islice(self._ids, index, None),
                        islice(self._ids, 0, max(index - 1, 0))),
                    self._cursor.IN_MAX)
                ffields = {name: ffields[name]}
                read_data = [{'id': i, name: self._cache[i][name]}
                    for i in ids
                    if i in self._cache and name in self._cache[i]]
            else:
                read_data = self.read(list(ids), ffields.keys())
            # create browse records for 'remote' models
            for data in read_data:
                for fname, field in ffields.iteritems():
                    fvalue = data[fname]
                    if field._type in ('many2one', 'one2one', 'one2many',
                            'many2many', 'reference'):
                        fvalue = instantiate(field, data[fname], data)
                    if data['id'] == self.id and fname == name:
                        value = fvalue
                    if (field._type not in ('many2one', 'one2one', 'one2many',
                                'many2many', 'reference', 'binary')
                            and not isinstance(field, fields.Function)):
                        continue
                    if data['id'] not in self._local_cache:
                        self._local_cache[data['id']] = {}
                    self._local_cache[data['id']][fname] = fvalue
                    if (field._type not in ('many2one', 'reference')
                            or field.context
                            or getattr(field, 'datetime_field', None)
                            or isinstance(field, fields.Function)):
                        del data[fname]
                if data['id'] not in self._cache:
                    self._cache[data['id']] = {}
                self._cache[data['id']].update(data)
        return value

    @property
    def _save_values(self):
        values = {}
        if not self._values:
            return values
        for fname, value in self._values.iteritems():
            field = self._fields[fname]
            if field._type in ('many2one', 'one2one', 'reference'):
                if value:
                    if value.id < 0 and field._type != 'reference':
                        value.save()
                    if field._type == 'reference':
                        value = str(value)
                    else:
                        value = value.id
            if field._type in ('one2many', 'many2many'):
                targets = value
                if self.id >= 0:
                    _values, self._values = self._values, None
                    try:
                        to_remove = [t.id for t in getattr(self, fname)]
                    finally:
                        self._values = _values
                else:
                    to_remove = []
                to_add = []
                to_create = []
                to_write = []
                for target in targets:
                    if target.id < 0:
                        if field._type == 'one2many':
                            # Don't store old target link
                            setattr(target, field.field, None)
                        to_create.append(target._save_values)
                    else:
                        if target.id in to_remove:
                            to_remove.remove(target.id)
                        else:
                            to_add.append(target.id)
                        target_values = target._save_values
                        if target_values:
                            to_write.append(
                                ('write', [target.id], target_values))
                value = []
                if to_remove:
                    value.append(('remove', to_remove))
                if to_add:
                    value.append(('add', to_add))
                if to_create:
                    value.append(('create', to_create))
                if to_write:
                    value.extend(to_write)
            values[fname] = value
        return values

    @dualmethod
    def save(cls, records):
        if not records:
            return
        values = {}
        save_values = {}
        to_create = []
        to_write = []
        cursor = records[0]._cursor
        user = records[0]._user
        context = records[0]._context
        for record in records:
            assert cursor == record._cursor
            assert user == record._user
            assert context == record._context
            save_values[record] = record._save_values
            values[record] = record._values
            record._values = None
            if record.id is None or record.id < 0:
                to_create.append(record)
            elif save_values[record]:
                to_write.append(record)
        transaction = Transaction()
        try:
            with transaction.set_cursor(cursor), \
                    transaction.set_user(user), \
                    transaction.set_context(context):
                if to_create:
                    news = cls.create([save_values[r] for r in to_create])
                    for record, new in izip(to_create, news):
                        record._ids.remove(record.id)
                        record.id = new.id
                        record._ids.append(record.id)
                if to_write:
                    cls.write(*sum(
                            (([r], save_values[r]) for r in to_write), ()))
        except:
            for record in records:
                record._values = values[record]
            raise
        for record in records:
            record._init_values = None


class EvalEnvironment(dict):

    def __init__(self, record, Model):
        super(EvalEnvironment, self).__init__()
        self._record = record
        self._model = Model

    def __getitem__(self, item):
        if item.startswith('_parent_'):
            field = item[8:]
            model_name = self._model._fields[field].model_name
            ParentModel = Pool().get(model_name)
            return EvalEnvironment(getattr(self._record, field), ParentModel)
        if item in self._model._fields:
            value = getattr(self._record, item)
            if isinstance(value, Model):
                if self._model._fields[item]._type == 'reference':
                    return str(value)
                return value.id
            elif isinstance(value, (list, tuple)):
                return [r.id for r in value]
            else:
                return value
        return super(EvalEnvironment, self).__getitem__(item)

    def __getattr__(self, item):
        try:
            return self.__getitem__(item)
        except KeyError, exception:
            raise AttributeError(*exception.args)

    def get(self, item, default=None):
        try:
            return self.__getitem__(item)
        except Exception:
            pass
        return super(EvalEnvironment, self).get(item, default)

    def __nonzero__(self):
        return bool(self._record)
