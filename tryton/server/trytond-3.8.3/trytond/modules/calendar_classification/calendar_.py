# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import vobject

from trytond.tools import reduce_ids, grouped_slice
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta


__all__ = ['Event']
__metaclass__ = PoolMeta


class Event:
    __name__ = 'calendar.event'

    @classmethod
    def __setup__(cls):
        super(Event, cls).__setup__()
        cls._error_messages.update({
            'transparent': 'Free',
            'opaque': 'Busy',
            })

    @classmethod
    def search(cls, domain, offset=0, limit=None, order=None, count=False,
            query=False):
        if Transaction().user:
            domain = domain[:]
            domain = [domain,
                ['OR',
                    [
                        ('classification', '=', 'private'),
                        ['OR',
                            ('calendar.owner', '=', Transaction().user),
                            ('calendar.write_users', '=', Transaction().user),
                            ],
                        ],
                    ('classification', '!=', 'private'),
                    ],
                ]
        records = super(Event, cls).search(domain, offset=offset, limit=limit,
            order=order, count=count, query=query)

        if Transaction().user:
            # Clear the cache as it was not cleaned for confidential
            cache = Transaction().cursor.get_cache()
            cache.pop(cls.__name__, None)
        return records

    @classmethod
    def create(cls, vlist):
        events = super(Event, cls).create(vlist)
        if (cls.search([('id', 'in', [x.id for x in events])], count=True)
                != len(events)):
            cls.raise_user_error('access_error', cls.__doc__)
        return events

    @classmethod
    def _clean_confidential(cls, record, transp):
        '''
        Clean confidential record
        '''
        summary = cls.raise_user_error(transp, raise_exception=False)
        if 'summary' in record:
            record['summary'] = summary

        vevent = None
        if 'vevent' in record:
            vevent = record['vevent']
            if vevent:
                vevent = vobject.readOne(str(vevent))
                if hasattr(vevent, 'summary'):
                    vevent.summary.value = summary

        for field, value in (
                ('description', ''),
                ('categories', []),
                ('location', None),
                ('status', ''),
                ('organizer', ''),
                ('attendees', []),
                ('alarms', [])):
            if field in record:
                record[field] = value
            if field + '.rec_name' in record:
                record[field + '.rec_name'] = ''
            if vevent:
                if hasattr(vevent, field):
                    delattr(vevent, field)
        if vevent:
            record['vevent'] = vevent.serialize()

    @classmethod
    def read(cls, ids, fields_names=None):
        Rule = Pool().get('ir.rule')
        cursor = Transaction().cursor
        table = cls.__table__()
        if len(set(ids)) != cls.search([('id', 'in', ids)],
                count=True):
            cls.raise_user_error('access_error', cls.__doc__)

        writable_ids = []
        domain = Rule.query_get(cls.__name__, mode='write')
        if domain:
            for sub_ids in grouped_slice(ids):
                red_sql = reduce_ids(table.id, sub_ids)
                cursor.execute(*table.select(table.id,
                        where=red_sql & table.id.in_(domain)))
                writable_ids.extend(x[0] for x in cursor.fetchall())
        else:
            writable_ids = ids
        writable_ids = set(writable_ids)

        if fields_names is None:
            fields_names = []
        fields_names = fields_names[:]
        to_remove = set()
        for field in ('classification', 'calendar', 'transp'):
            if field not in fields_names:
                fields_names.append(field)
                to_remove.add(field)
        res = super(Event, cls).read(ids, fields_names=fields_names)
        for record in res:
            if record['classification'] == 'confidential' \
                    and record['id'] not in writable_ids:
                cls._clean_confidential(record, record['transp'])
            for field in to_remove:
                del record[field]
        return res

    @classmethod
    def write(cls, *args):
        for events in args[::2]:
            if len(set(events)) != cls.search([('id', 'in', map(int, events))],
                    count=True):
                cls.raise_user_error('access_error', cls.__doc__)
        super(Event, cls).write(*args)
        for events in args[::2]:
            if len(set(events)) != cls.search([('id', 'in', map(int, events))],
                    count=True):
                cls.raise_user_error('access_error', cls.__doc__)

    @classmethod
    def delete(cls, events):
        if len(set(events)) != cls.search([('id', 'in', map(int, events))],
                count=True):
            cls.raise_user_error('access_error', cls.__doc__)
        super(Event, cls).delete(events)
