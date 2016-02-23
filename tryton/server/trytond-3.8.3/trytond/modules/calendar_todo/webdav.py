# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import vobject
import urllib
from pywebdav.lib.errors import DAV_NotFound, DAV_Forbidden
from sql.functions import Extract
from sql.conditionals import Coalesce
from sql.aggregate import Max

from trytond.tools import reduce_ids, grouped_slice
from trytond.transaction import Transaction
from trytond.cache import Cache
from trytond.pool import Pool, PoolMeta

__all__ = ['Collection']
__metaclass__ = PoolMeta


class Collection:
    __name__ = "webdav.collection"
    _todo_cache = Cache('webdav_collection.todo')

    @classmethod
    def todo(cls, uri, calendar_id=False):
        '''
        Return the todo id in the uri
        '''
        Todo = Pool().get('calendar.todo')

        if uri and uri.startswith('Calendars/'):
            calendar, todo_uri = (uri[10:].split('/', 1) + [None])[0:2]
            if not calendar_id:
                calendar_id = cls.calendar(uri)
                if not calendar_id:
                    return None
            todos = Todo.search([
                ('calendar', '=', calendar_id),
                ('uuid', '=', todo_uri[:-4]),
                ('parent', '=', None),
                ], limit=1)
            if todos:
                return todos[0].id

    @classmethod
    def _caldav_filter_domain_todo(cls, filter):
        '''
        Return a domain for caldav filter on todo
        '''
        res = []
        if not filter:
            return []
        if filter.localName == 'principal-property-search':
            return [('id', '=', 0)]
        elif filter.localName == 'calendar-query':
            calendar_filter = None
            for e in filter.childNodes:
                if e.nodeType == e.TEXT_NODE:
                    continue
                if e.localName == 'filter':
                    calendar_filter = e
                    break
            if calendar_filter is None:
                return []
            for vcalendar_filter in calendar_filter.childNodes:
                if vcalendar_filter.nodeType == vcalendar_filter.TEXT_NODE:
                    continue
                if vcalendar_filter.getAttribute('name') != 'VCALENDAR':
                    return [('id', '=', 0)]
                vtodo_filter = None
                for vtodo_filter in vcalendar_filter.childNodes:
                    if vtodo_filter.nodeType == vtodo_filter.TEXT_NODE:
                        vtodo_filter = None
                        continue
                    if vtodo_filter.localName == 'comp-filter':
                        if vtodo_filter.getAttribute('name') != 'VTODO':
                            vtodo_filter = None
                            continue
                        break
                if vtodo_filter is None:
                    return [('id', '=', 0)]
                break
            return []
        elif filter.localName == 'calendar-multiget':
            ids = []
            for e in filter.childNodes:
                if e.nodeType == e.TEXT_NODE:
                    continue
                if e.localName == 'href':
                    if not e.firstChild:
                        continue
                    uri = e.firstChild.data
                    dbname, uri = (uri.lstrip('/').split('/', 1) + [None])[0:2]
                    if not dbname:
                        continue
                    dbname == urllib.unquote_plus(dbname)
                    if dbname != Transaction().cursor.database_name:
                        continue
                    if uri:
                        uri = urllib.unquote_plus(uri)
                    todo_id = cls.todo(uri)
                    if todo_id:
                        ids.append(todo_id)
            return [('id', 'in', ids)]
        return res

    @classmethod
    def get_childs(cls, uri, filter=None, cache=None):
        Todo = Pool().get('calendar.todo')

        res = super(Collection, cls).get_childs(uri, filter=filter,
                cache=cache)

        if uri and (uri not in ('Calendars', 'Calendars/')) and \
                uri.startswith('Calendars/'):
            calendar_id = cls.calendar(uri)
            if calendar_id and not (uri[10:].split('/', 1) + [None])[1]:
                domain = cls._caldav_filter_domain_todo(filter)
                todos = Todo.search([
                    ('calendar', '=', calendar_id),
                    domain,
                    ])
                if cache is not None:
                    cache.setdefault('_calendar', {})
                    cache['_calendar'].setdefault(Todo.__name__, {})
                    for todo in todos:
                        cache['_calendar'][Todo.__name__][todo.id] = {}
                return res + [x.uuid + '.ics' for x in todos]

        return res

    @classmethod
    def get_resourcetype(cls, uri, cache=None):
        from pywebdav.lib.constants import COLLECTION, OBJECT
        if uri in ('Calendars', 'Calendars/'):
            return COLLECTION
        calendar_id = cls.calendar(uri)
        if calendar_id:
            if not (uri[10:].split('/', 1) + [None])[1]:
                return COLLECTION
            if cls.todo(uri, calendar_id=calendar_id):
                return OBJECT
        elif cls.calendar(uri, ics=True):
            return OBJECT
        return super(Collection, cls).get_resourcetype(uri, cache=cache)

    @classmethod
    def get_contenttype(cls, uri, cache=None):
        if (cls.todo(uri)
                or cls.calendar(uri, ics=True)):
            return 'text/calendar'
        return super(Collection, cls).get_contenttype(uri, cache=cache)

    @classmethod
    def get_creationdate(cls, uri, cache=None):
        Todo = Pool().get('calendar.todo')
        todo = Todo.__table__()

        cursor = Transaction().cursor

        calendar_id = cls.calendar(uri)
        if not calendar_id:
            calendar_id = cls.calendar(uri, ics=True)
        if calendar_id and (uri[10:].split('/', 1) + [None])[1]:

            todo_id = cls.todo(uri, calendar_id=calendar_id)
            if todo_id:
                if cache is not None:
                    cache.setdefault('_calendar', {})
                    cache['_calendar'].setdefault(Todo.__name__, {})
                    ids = cache['_calendar'][Todo.__name__].keys()
                    if todo_id not in ids:
                        ids.append(todo_id)
                    elif 'creationdate' in cache['_calendar'][
                            Todo.__name__][todo_id]:
                        return cache['_calendar'][Todo.__name__][
                            todo_id]['creationdate']
                else:
                    ids = [todo_id]
                res = None
                for sub_ids in grouped_slice(ids):
                    red_sql = reduce_ids(todo.id, sub_ids)
                    cursor.execute(*todo.select(todo.id,
                            Extract('EPOCH', todo.create_date),
                            where=red_sql))
                    for todo_id2, date in cursor.fetchall():
                        if todo_id2 == todo_id:
                            res = date
                        if cache is not None:
                            cache['_calendar'][Todo.__name__]\
                                .setdefault(todo_id2, {})
                            cache['_calendar'][Todo.__name__][
                                todo_id2]['creationdate'] = date
                if res is not None:
                    return res

        return super(Collection, cls).get_creationdate(uri, cache=cache)

    @classmethod
    def get_lastmodified(cls, uri, cache=None):
        Todo = Pool().get('calendar.todo')
        todo = Todo.__table__()

        cursor = Transaction().cursor

        calendar_id = cls.calendar(uri)
        if calendar_id and (uri[10:].split('/', 1) + [None])[1]:
            todo_id = cls.todo(uri, calendar_id=calendar_id)
            if todo_id:
                if cache is not None:
                    cache.setdefault('_calendar', {})
                    cache['_calendar'].setdefault(Todo.__name__, {})
                    ids = cache['_calendar'][Todo.__name__].keys()
                    if todo_id not in ids:
                        ids.append(todo_id)
                    elif 'lastmodified' in cache['_calendar'][
                            Todo.__name__][todo_id]:
                        return cache['_calendar'][Todo.__name__][
                            todo_id]['lastmodified']
                else:
                    ids = [todo_id]
                res = None
                for sub_ids in grouped_slice(ids, cursor.IN_MAX / 2):
                    red_id_sql = reduce_ids(todo.id, sub_ids)
                    red_parent_sql = reduce_ids(todo.parent, sub_ids)
                    cursor.execute(*todo.select(Coalesce(todo.parent, todo.id),
                            Max(Extract('EPOCH', Coalesce(todo.write_date,
                                        todo.create_date))),
                            where=red_id_sql | red_parent_sql,
                            group_by=(todo.parent, todo.id)))
                    for todo_id2, date in cursor.fetchall():
                        if todo_id2 == todo_id:
                            res = date
                        if cache is not None:
                            cache['_calendar'][Todo.__name__]\
                                .setdefault(todo_id2, {})
                            cache['_calendar'][Todo.__name__][
                                todo_id2]['lastmodified'] = date
                if res is not None:
                    return res

        return super(Collection, cls).get_lastmodified(uri, cache=cache)

    @classmethod
    def get_data(cls, uri, cache=None):
        Todo = Pool().get('calendar.todo')

        calendar_id = cls.calendar(uri)
        if calendar_id:
            if not (uri[10:].split('/', 1) + [None])[1]:
                raise DAV_NotFound
            todo_id = cls.todo(uri, calendar_id=calendar_id)
            if not todo_id:
                return super(Collection, cls).get_data(uri, cache=cache)
            ical = Todo(todo_id).todo2ical()
            return ical.serialize()

        return super(Collection, cls).get_data(uri, cache=cache)

    @classmethod
    def put(cls, uri, data, content_type, cache=None):
        pool = Pool()
        Todo = pool.get('calendar.todo')
        Calendar = pool.get('calendar.calendar')

        calendar_id = cls.calendar(uri)
        if calendar_id:
            if not (uri[10:].split('/', 1) + [None])[1]:
                raise DAV_Forbidden
            todo_id = cls.todo(uri, calendar_id=calendar_id)
            ical = vobject.readOne(data)
            if not hasattr(ical, 'vtodo'):
                return super(Collection, cls).put(uri, data, content_type)

            if not todo_id:

                values = Todo.ical2values(None, ical, calendar_id)
                todo, = Todo.create([values])
                calendar = Calendar(calendar_id)
                return Transaction().cursor.database_name + '/Calendars/' + \
                    calendar.name + '/' + todo.uuid + '.ics'
            else:
                values = Todo.ical2values(todo_id, ical, calendar_id)
                Todo.write([Todo(todo_id)], values)
                return

        return super(Collection, cls).put(uri, data, content_type)

    @classmethod
    def rm(cls, uri, cache=None):
        Todo = Pool().get('calendar.todo')

        calendar_id = cls.calendar(uri)
        if calendar_id:
            if not (uri[10:].split('/', 1) + [None])[1]:
                raise DAV_Forbidden
            todo_id = cls.todo(uri, calendar_id=calendar_id)
            if todo_id:
                try:
                    Todo.delete([Todo(todo_id)])
                except Exception:
                    raise DAV_Forbidden
                return 200
        return super(Collection, cls).rm(uri, cache=cache)

    @classmethod
    def exists(cls, uri, cache=None):
        if uri in ('Calendars', 'Calendars/'):
            return 1
        calendar_id = cls.calendar(uri)
        if calendar_id:
            if not (uri[10:].split('/', 1) + [None])[1]:
                return 1
            if cls.todo(uri, calendar_id=calendar_id):
                return 1
        return super(Collection, cls).exists(uri, cache=cache)
