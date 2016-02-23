# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import uuid
import vobject
import dateutil.tz
import pytz
import datetime
import xml.dom.minidom
from sql import Table, Column

from trytond.model import ModelSQL, ModelView, fields, Unique
from trytond.tools import reduce_ids
from trytond import backend
from trytond.pyson import Eval, If, Bool, PYSONEncoder
from trytond.transaction import Transaction
from trytond.pool import Pool
from trytond.modules.calendar import AlarmMixin, DateMixin, RRuleMixin, \
    AttendeeMixin

__all__ = ['Todo', 'TodoCategory', 'TodoRDate', 'TodoRRule', 'TodoExDate',
    'TodoExRule', 'TodoAttendee', 'TodoAlarm']

tzlocal = dateutil.tz.tzlocal()
tzutc = dateutil.tz.tzutc()

domimpl = xml.dom.minidom.getDOMImplementation()


class Todo(ModelSQL, ModelView):
    "Todo"
    __name__ = 'calendar.todo'
    _rec_name = 'uuid'
    calendar = fields.Many2One('calendar.calendar', 'Calendar',
            required=True, select=True, ondelete="CASCADE")
    alarms = fields.One2Many('calendar.todo.alarm', 'todo', 'Alarms')
    classification = fields.Selection([
        ('public', 'Public'),
        ('private', 'Private'),
        ('confidential', 'Confidential'),
        ], 'Classification', required=True)
    completed = fields.DateTime('Completed',
        states={
            'readonly': Eval('status') != 'completed',
            }, depends=['status'])
    description = fields.Text('Description')
    dtstart = fields.DateTime('Start Date', select=True)
    location = fields.Many2One('calendar.location', 'Location')
    organizer = fields.Char('Organizer', states={
            'required': If(Bool(Eval('attendees')),
                ~Eval('parent'), False),
            }, depends=['attendees', 'parent'])
    attendees = fields.One2Many('calendar.todo.attendee', 'todo',
            'Attendees')
    percent_complete = fields.Integer('Percent complete', required=True,
        states={
            'readonly': ~Eval('status').in_(['needs-action', 'in-process']),
            }, depends=['status'])
    occurences = fields.One2Many('calendar.todo', 'parent', 'Occurences',
            domain=[
                ('uuid', '=', Eval('uuid')),
                ('calendar', '=', Eval('calendar')),
            ],
            states={
                'invisible': Bool(Eval('parent')),
            }, depends=['uuid', 'calendar', 'parent'])
    recurrence = fields.DateTime('Recurrence', select=True, states={
            'invisible': ~Eval('_parent_parent'),
            'required': Bool(Eval('_parent_parent')),
            }, depends=['parent'])
    sequence = fields.Integer('Sequence', required=True)
    parent = fields.Many2One('calendar.todo', 'Parent',
            domain=[
                ('uuid', '=', Eval('uuid')),
                ('parent', '=', None),
                ('calendar', '=', Eval('calendar'))
            ],
            ondelete='CASCADE', depends=['uuid', 'calendar'])
    timezone = fields.Selection('timezones', 'Timezone')
    status = fields.Selection([
        ('', ''),
        ('needs-action', 'Needs-Action'),
        ('completed', 'Completed'),
        ('in-process', 'In-Process'),
        ('cancelled', 'Cancelled'),
        ], 'Status')
    summary = fields.Char('Summary')
    uuid = fields.Char('UUID', required=True,
            help='Universally Unique Identifier', select=True)
    due = fields.DateTime('Due Date', select=True)
    categories = fields.Many2Many('calendar.todo-calendar.category',
            'todo', 'category', 'Categories')
    exdates = fields.One2Many('calendar.todo.exdate', 'todo',
        'Exception Dates',
        states={
            'invisible': Bool(Eval('parent')),
            }, depends=['parent'])
    exrules = fields.One2Many('calendar.todo.exrule', 'todo',
        'Exception Rules',
        states={
            'invisible': Bool(Eval('parent')),
            }, depends=['parent'])
    rdates = fields.One2Many('calendar.todo.rdate', 'todo', 'Recurrence Dates',
            states={
                'invisible': Bool(Eval('parent')),
            }, depends=['parent'])
    rrules = fields.One2Many('calendar.todo.rrule', 'todo', 'Recurrence Rules',
            states={
                'invisible': Bool(Eval('parent')),
            }, depends=['parent'])
    vtodo = fields.Binary('vtodo')

    @classmethod
    def __setup__(cls):
        super(Todo, cls).__setup__()
        t = cls.__table__()
        cls._sql_constraints = [
            # XXX should be unique across all componenets
            ('uuid_recurrence_uniq',
                Unique(t, t.uuid, t.calendar, t.recurrence),
                'UUID and recurrence must be unique in a calendar.'),
            ]
        cls._error_messages.update({
                'invalid_recurrence': 'Todo "%s" can not be recurrent.',
                })

    @classmethod
    def __register__(cls, module_name):
        pool = Pool()
        # Migrate from 1.4: remove classification_public
        ModelData = pool.get('ir.model.data')
        Rule = pool.get('ir.rule')
        with Transaction().set_user(0):
            models_data = ModelData.search([
                ('fs_id', '=', 'rule_group_read_todo_line3'),
                ('module', '=', module_name),
                ], limit=1)
            if models_data:
                model_data, = models_data
                Rule.delete([Rule(model_data.db_id)])
        super(Todo, cls).__register__(module_name)

    @staticmethod
    def default_uuid():
        return str(uuid.uuid4())

    @staticmethod
    def default_sequence():
        return 0

    @staticmethod
    def default_classification():
        return 'public'

    @staticmethod
    def default_percent_complete():
        return 0

    @fields.depends('status', 'completed', 'percent_complete')
    def on_change_status(self):
        if not self.status:
            return
        if self.status == 'completed':
            self.percent_complete = 100
            if not self.completed:
                self.completed = datetime.datetime.now()

    @staticmethod
    def timezones():
        return [(x, x) for x in pytz.common_timezones] + [('', '')]

    @classmethod
    def validate(cls, todos):
        super(Todo, cls).validate(todos)
        for todo in todos:
            todo.check_recurrence()

    def check_recurrence(self):
        '''
        Check the recurrence is not recurrent.
        '''
        if not self.parent:
            return True
        if (self.rdates
                or self.rrules
                or self.exdates
                or self.exrules
                or self.occurences):
            self.raise_user_error('invalid_recurrence', (self.rec_name,))

    @classmethod
    def view_attributes(cls):
        return [('//page[@id="occurences"]', 'states', {
                    'invisible': Bool(Eval('_parent_parent')),
                    })]

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Calendar = pool.get('calendar.calendar')
        Collection = pool.get('webdav.collection')

        todos = super(Todo, cls).create(vlist)
        for todo in todos:
            if (todo.calendar.owner
                    and (todo.organizer == todo.calendar.owner.email
                        or (todo.parent
                            and todo.parent.organizer
                            == todo.parent.calendar.owner.email))):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.status != 'declined'
                            and x.email != todo.organizer]
                else:
                    attendee_emails = [x.email for x in todo.parent.attendees
                            if x.status != 'declined'
                            and x.email != todo.parent.organizer]
                if attendee_emails:
                    with Transaction().set_user(0):
                        calendars = Calendar.search([
                            ('owner.email', 'in', attendee_emails),
                            ])
                        if not todo.recurrence:
                            for calendar in calendars:
                                new_todo, = cls.copy([todo], default={
                                    'calendar': calendar.id,
                                    'occurences': None,
                                    'uuid': todo.uuid,
                                    })
                                for occurence in todo.occurences:
                                    cls.copy([occurence], default={
                                        'calendar': calendar.id,
                                        'parent': new_todo.id,
                                        'uuid': occurence.uuid,
                                        })
                        else:
                            parents = cls.search([
                                    ('uuid', '=', todo.uuid),
                                    ('calendar.owner.email', 'in',
                                        attendee_emails),
                                    ('id', '!=', todo.id),
                                    ('recurrence', '=', None),
                                    ])
                            for parent in parents:
                                cls.copy([todo], default={
                                    'calendar': parent.calendar.id,
                                    'parent': parent.id,
                                    'uuid': todo.uuid,
                                    })
        # Restart the cache for todo
        Collection._todo_cache.clear()
        return todos

    def _todo2update(self):
        res = {}
        res['summary'] = self.summary
        res['description'] = self.description
        res['dtstart'] = self.dtstart
        res['percent_complete'] = self.percent_complete
        res['completed'] = self.completed
        res['location'] = self.location.id
        res['status'] = self.status
        res['organizer'] = self.organizer
        res['rdates'] = [('delete', [r.id for r in self.rdates])]
        to_create = [rdate._date2update() for rdate in self.rdates]
        if to_create:
            res['rdates'].append(('create', to_create))
        res['exdates'] = [('delete', [r.id for r in self.exdates])]
        to_create = [exdate._date2update() for exdate in self.exdates]
        if to_create:
            res['exdates'].append(('create', to_create))
        res['rrules'] = [('delete', [r.id for r in self.rrules])]
        to_create = [rrule._rule2update() for rrule in self.rrules]
        if to_create:
            res['rrules'].append(('create', to_create))
        res['exrules'] = [('delete', [r.id for r in self.exrules])]
        to_create = [exrule._rule2update() for exrule in self.exrules]
        if to_create:
            res['exrules'].append(('create', to_create))
        return res

    @classmethod
    def write(cls, *args):
        pool = Pool()
        Calendar = pool.get('calendar.calendar')
        Collection = pool.get('webdav.collection')
        table = cls.__table__()

        cursor = Transaction().cursor

        actions = iter(args)
        args = []
        for todos, values in zip(actions, actions):
            values = values.copy()
            if 'sequence' in values:
                del values['sequence']
            args.extend((todos, values))

        super(Todo, cls).write(*args)

        ids = [t.id for t in todos]
        for i in range(0, len(ids), cursor.IN_MAX):
            sub_ids = ids[i:i + cursor.IN_MAX]
            red_sql = reduce_ids(table.id, sub_ids)
            cursor.execute(*table.update(
                    columns=[table.sequence],
                    values=[table.sequence + 1],
                    where=red_sql))

        actions = iter(args)
        for todos, values in zip(actions, actions):
            if not values:
                continue
            for todo in todos:
                if (todo.calendar.owner
                        and (todo.organizer == todo.calendar.owner.email
                            or (todo.parent
                                and todo.parent.organizer
                                == todo.calendar.owner.email))):
                    if todo.organizer == todo.calendar.owner.email:
                        attendee_emails = [x.email for x in todo.attendees
                                if x.status != 'declined'
                                and x.email != todo.organizer]
                    else:
                        attendee_emails = [
                            x.email for x in todo.parent.attendees
                            if x.status != 'declined'
                            and x.email != todo.parent.organizer]
                    if attendee_emails:
                        with Transaction().set_user(0):
                            todo2s = cls.search([
                                    ('uuid', '=', todo.uuid),
                                    ('calendar.owner.email', 'in',
                                        attendee_emails),
                                    ('id', '!=', todo.id),
                                    ('recurrence', '=', todo.recurrence),
                                    ])
                        for todo2 in todo2s:
                            if todo2.calendar.owner.email in attendee_emails:
                                attendee_emails.remove(
                                    todo2.calendar.owner.email)
                        with Transaction().set_user(0):
                            cls.write(todos, todo._todo2update())
                    if attendee_emails:
                        with Transaction().set_user(0):
                            calendars = Calendar.search([
                                ('owner.email', 'in', attendee_emails),
                                ])
                            if not todo.recurrence:
                                for calendar in calendars:
                                    new_todo, = cls.copy([todo], default={
                                        'calendar': calendar.id,
                                        'occurences': None,
                                        'uuid': todo.uuid,
                                        })
                                    for occurence in todo.occurences:
                                        cls.copy([occurence], default={
                                            'calendar': calendar.id,
                                            'parent': new_todo.id,
                                            'uuid': occurence.uuid,
                                            })
                            else:
                                parents = cls.search([
                                        ('uuid', '=', todo.uuid),
                                        ('calendar.owner.email', 'in',
                                            attendee_emails),
                                        ('id', '!=', todo.id),
                                        ('recurrence', '=', None),
                                        ])
                                for parent in parents:
                                    cls.copy([todo], default={
                                        'calendar': parent.calendar.id,
                                        'parent': parent.id,
                                        'uuid': todo.uuid,
                                        })
        # Restart the cache for todo
        Collection._todo_cache.clear()

    @classmethod
    def delete(cls, todos):
        pool = Pool()
        Attendee = pool.get('calendar.todo.attendee')
        Collection = pool.get('webdav.collection')

        for todo in todos:
            if (todo.calendar.owner
                    and (todo.organizer == todo.calendar.owner.email
                        or (todo.parent
                            and todo.parent.organizer
                            == todo.calendar.owner.email))):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.email != todo.organizer]
                else:
                    attendee_emails = [x.email for x in todo.parent.attendees
                            if x.email != todo.parent.organizer]
                if attendee_emails:
                    with Transaction().set_user(0):
                        todos_delete = cls.search([
                            ('uuid', '=', todo.uuid),
                            ('calendar.owner.email', 'in', attendee_emails),
                            ('id', '!=', todo.id),
                            ('recurrence', '=', todo.recurrence),
                            ])
                        cls.delete(todos_delete)
            elif todo.organizer \
                    or (todo.parent and todo.parent.organizer):
                if todo.organizer:
                    organizer = todo.organizer
                else:
                    organizer = todo.parent.organizer
                with Transaction().set_user(0):
                    todo2s = cls.search([
                        ('uuid', '=', todo.uuid),
                        ('calendar.owner.email', '=', organizer),
                        ('id', '!=', todo.id),
                        ('recurrence', '=', todo.recurrence),
                        ], limit=1)
                    if todo2s:
                        todo2, = todo2s
                        for attendee in todo2.attendees:
                            if attendee.email == todo.calendar.owner.email:
                                Attendee.write([attendee], {
                                    'status': 'declined',
                                    })
        super(Todo, cls).delete(todos)
        # Restart the cache for todo
        Collection._todo_cache.clear()

    @classmethod
    def copy(cls, todos, default=None):
        if default is None:
            default = {}

        new_todos = []
        for todo in todos:
            current_default = default.copy()
            current_default.setdefault('uuid', cls.default_uuid())
            new_todo, = super(Todo, cls).copy([todo], default=current_default)
            new_todos.append(new_todo)
        return new_todos

    @classmethod
    def ical2values(cls, todo_id, ical, calendar_id, vtodo=None):
        '''
        Convert iCalendar to values for create or write with:
        todo_id: the todo id for write or None for create
        ical: a ical instance of vobject
        calendar_id: the calendar id of the todo
        vtodo: the vtodo of the ical to use if None use the first one
        '''
        pool = Pool()
        Category = pool.get('calendar.category')
        Location = pool.get('calendar.location')
        Alarm = pool.get('calendar.todo.alarm')
        Attendee = pool.get('calendar.todo.attendee')
        Rdate = pool.get('calendar.todo.rdate')
        Exdate = pool.get('calendar.todo.exdate')
        Rrule = pool.get('calendar.todo.rrule')
        Exrule = pool.get('calendar.todo.exrule')

        vtodos = []
        if not vtodo:
            vtodo = ical.vtodo

            for i in ical.getChildren():
                if i.name == 'VTODO' \
                        and i != vtodo:
                    vtodos.append(i)

        todo = None
        if todo_id:
            todo = cls(todo_id)
        res = {}
        if not todo:
            if hasattr(vtodo, 'uid'):
                res['uuid'] = vtodo.uid.value
            else:
                res['uuid'] = str(uuid.uuid4())
        if hasattr(vtodo, 'summary'):
            res['summary'] = vtodo.summary.value
        else:
            res['summary'] = None
        if hasattr(vtodo, 'description'):
            res['description'] = vtodo.description.value
        else:
            res['description'] = None
        if hasattr(vtodo, 'percent_complete'):
            res['percent_complete'] = int(vtodo.percent_complete.value)
        else:
            res['percent_complete'] = 0

        if hasattr(vtodo, 'completed'):
            if not isinstance(vtodo.completed.value, datetime.datetime):
                res['completed'] = datetime.datetime.combine(
                    vtodo.completed.value, datetime.time())
            else:
                if vtodo.completed.value.tzinfo:
                    res['completed'] = vtodo.completed.value.astimezone(
                        tzlocal)
                else:
                    res['completed'] = vtodo.completed.value

        if hasattr(vtodo, 'dtstart'):
            if not isinstance(vtodo.dtstart.value, datetime.datetime):
                res['dtstart'] = datetime.datetime.combine(vtodo.dtstart.value,
                        datetime.time())
            else:
                if vtodo.dtstart.value.tzinfo:
                    res['dtstart'] = vtodo.dtstart.value.astimezone(tzlocal)
                else:
                    res['dtstart'] = vtodo.dtstart.value

        if hasattr(vtodo, 'due'):
            if not isinstance(vtodo.due.value, datetime.datetime):
                res['due'] = datetime.datetime.combine(vtodo.due.value,
                        datetime.time())
            else:
                if vtodo.due.value.tzinfo:
                    res['due'] = vtodo.due.value.astimezone(tzlocal)
                else:
                    res['due'] = vtodo.due.value

        if hasattr(vtodo, 'recurrence-id'):
            if not isinstance(vtodo.recurrence_id.value, datetime.datetime):
                res['recurrence'] = datetime.datetime.combine(
                        vtodo.recurrence_id.value, datetime.time())
            else:
                if vtodo.recurrence_id.value.tzinfo:
                    res['recurrence'] = \
                        vtodo.recurrence_id.value.astimezone(tzlocal)
                else:
                    res['recurrence'] = vtodo.recurrence_id.value
        else:
            res['recurrence'] = None
        if hasattr(vtodo, 'status'):
            res['status'] = vtodo.status.value.lower()
        else:
            res['status'] = ''

        res['categories'] = []
        if todo:
            res['categories'] += [('remove', [c.id for c in todo.categories])]
        if hasattr(vtodo, 'categories'):
            categories = Category.search([
                ('name', 'in', [x for x in vtodo.categories.value]),
                ])
            category_names2ids = {}
            for category in categories:
                category_names2ids[category.name] = category.id
            to_create = []
            for category in vtodo.categories.value:
                if category not in category_names2ids:
                    to_create.append({
                            'name': category,
                            })
            if to_create:
                categories += Category.create(to_create)
            res['categories'] += [('add', [c.id for c in categories])]
        if hasattr(vtodo, 'class'):
            if getattr(vtodo, 'class').value.lower() in \
                    dict(cls.classification.selection):
                res['classification'] = getattr(vtodo, 'class').value.lower()
            else:
                res['classification'] = 'public'
        else:
            res['classification'] = 'public'
        if hasattr(vtodo, 'location'):
            locations = Location.search([
                ('name', '=', vtodo.location.value),
                ], limit=1)
            if not locations:
                location, = Location.create([{
                            'name': vtodo.location.value,
                            }])
            else:
                location, = locations
            res['location'] = location.id
        else:
            res['location'] = None

        res['calendar'] = calendar_id

        if hasattr(vtodo, 'organizer'):
            if vtodo.organizer.value.lower().startswith('mailto:'):
                res['organizer'] = vtodo.organizer.value[7:]
            else:
                res['organizer'] = vtodo.organizer.value
        else:
            res['organizer'] = None

        attendees_todel = {}
        if todo:
            for attendee in todo.attendees:
                attendees_todel[attendee.email] = attendee.id
        res['attendees'] = []
        if hasattr(vtodo, 'attendee'):
            to_create = []
            while vtodo.attendee_list:
                attendee = vtodo.attendee_list.pop()
                vals = Attendee.attendee2values(attendee)
                if vals['email'] in attendees_todel:
                    res['attendees'].append(('write',
                        attendees_todel[vals['email']], vals))
                    del attendees_todel[vals['email']]
                else:
                    to_create.append(vals)
            if to_create:
                res['attendees'].append(('create', to_create))
        res['attendees'].append(('delete', attendees_todel.values()))

        res['rdates'] = []
        if todo:
            res['rdates'].append(('delete', [x.id for x in todo.rdates]))
        if hasattr(vtodo, 'rdate'):
            to_create = []
            while vtodo.rdate_list:
                rdate = vtodo.rdate_list.pop()
                to_create += [Rdate.date2values(date) for date in rdate.value]
            if to_create:
                res['rdates'].append(('create', to_create))

        res['exdates'] = []
        if todo:
            res['exdates'].append(('delete', [x.id for x in todo.exdates]))
        if hasattr(vtodo, 'exdate'):
            to_create = []
            while vtodo.exdate_list:
                exdate = vtodo.exdate_list.pop()
                to_create += [Exdate.date2values(date)
                    for date in exdate.value]
            if to_create:
                res['exdates'].append(('create', to_create))

        res['rrules'] = []
        if todo:
            res['rrules'].append(('delete', [x.id for x in todo.rrules]))
        if hasattr(vtodo, 'rrule'):
            to_create = []
            while vtodo.rrule_list:
                rrule = vtodo.rrule_list.pop()
                to_create.append(Rrule.rule2values(rrule))
            if to_create:
                res['rrules'].append(('create', to_create))

        res['exrules'] = []
        if todo:
            res['exrules'].append(('delete', [x.id for x in todo.exrules]))
        if hasattr(vtodo, 'exrule'):
            to_create = []
            while vtodo.exrule_list:
                exrule = vtodo.exrule_list.pop()
                to_create.append(Exrule.rule2values(exrule))
            if to_create:
                res['exrules'].append(('create', to_create))

        if todo:
            res.setdefault('alarms', [])
            res['alarms'].append(('delete', [x.id for x in todo.alarms]))
        if hasattr(vtodo, 'valarm'):
            res.setdefault('alarms', [])
            to_create = []
            while vtodo.valarm_list:
                valarm = vtodo.valarm_list.pop()
                to_create.append(Alarm.valarm2values(valarm))
            if to_create:
                res['alarms'].append(('create', to_create))

        if hasattr(ical, 'vtimezone'):
            if ical.vtimezone.tzid.value in pytz.common_timezones:
                res['timezone'] = ical.vtimezone.tzid.value
            else:
                for timezone in pytz.common_timezones:
                    if ical.vtimezone.tzid.value.endswith(timezone):
                        res['timezone'] = timezone

        res['vtodo'] = vtodo.serialize()

        occurences_todel = []
        if todo:
            occurences_todel = [x.id for x in todo.occurences]
        to_create = []
        for vtodo in vtodos:
            todo_id = None
            if todo:
                for occurence in todo.occurences:
                    if occurence.recurrence.replace(tzinfo=tzlocal) \
                            == vtodo.recurrence_id.value:
                        todo_id = occurence.id
                        occurences_todel.remove(occurence.id)
            vals = cls.ical2values(todo_id, ical, calendar_id, vtodo=vtodo)
            if todo:
                vals['uuid'] = todo.uuid
            else:
                vals['uuid'] = res['uuid']
            res.setdefault('occurences', [])
            if todo_id:
                res['occurences'].append(('write', todo_id, vals))
            else:
                to_create.append(vals)
        if to_create:
            res['occurences'].append(('create', to_create))
        if occurences_todel:
            res.setdefault('occurences', [])
            res['occurences'].append(('delete', occurences_todel))
        return res

    def todo2ical(self):
        '''
        Return an iCalendar instance of vobject for todo
        '''
        if self.timezone:
            tztodo = dateutil.tz.gettz(self.timezone)
        else:
            tztodo = tzlocal

        ical = vobject.iCalendar()
        vtodo = ical.add('vtodo')
        if self.vtodo:
            ical.vtodo = vobject.readOne(str(self.vtodo))
            vtodo = ical.vtodo
            ical.vtodo.transformToNative()
        if self.summary:
            if not hasattr(vtodo, 'summary'):
                vtodo.add('summary')
            vtodo.summary.value = self.summary
        elif hasattr(vtodo, 'summary'):
            del vtodo.summary
        if self.percent_complete:
            if not hasattr(vtodo, 'percent-complete'):
                vtodo.add('percent-complete')
            vtodo.percent_complete.value = str(self.percent_complete)
        elif hasattr(vtodo, 'percent_complete'):
            del vtodo.percent_complete
        if self.description:
            if not hasattr(vtodo, 'description'):
                vtodo.add('description')
            vtodo.description.value = self.description
        elif hasattr(vtodo, 'description'):
            del vtodo.description

        if self.completed:
            if not hasattr(vtodo, 'completed'):
                vtodo.add('completed')
            vtodo.completed.value = self.completed.replace(tzinfo=tzlocal)\
                .astimezone(tzutc)
        elif hasattr(vtodo, 'completed'):
            del vtodo.completed

        if self.dtstart:
            if not hasattr(vtodo, 'dtstart'):
                vtodo.add('dtstart')
            vtodo.dtstart.value = self.dtstart.replace(tzinfo=tzlocal)\
                .astimezone(tztodo)
        elif hasattr(vtodo, 'dtstart'):
            del vtodo.dtstart

        if self.due:
            if not hasattr(vtodo, 'due'):
                vtodo.add('due')
            vtodo.due.value = self.due.replace(tzinfo=tzlocal)\
                .astimezone(tztodo)
        elif hasattr(vtodo, 'due'):
            del vtodo.due

        if not hasattr(vtodo, 'created'):
            vtodo.add('created')
        vtodo.created.value = self.create_date.replace(
            tzinfo=tzlocal).astimezone(tztodo)
        if not hasattr(vtodo, 'dtstamp'):
            vtodo.add('dtstamp')
        date = self.write_date or self.create_date
        vtodo.dtstamp.value = date.replace(tzinfo=tzlocal).astimezone(tztodo)
        if not hasattr(vtodo, 'last-modified'):
            vtodo.add('last-modified')
        vtodo.last_modified.value = date.replace(
            tzinfo=tzlocal).astimezone(tztodo)
        if self.recurrence and self.parent:
            if not hasattr(vtodo, 'recurrence-id'):
                vtodo.add('recurrence-id')
            vtodo.recurrence_id.value = self.recurrence\
                .replace(tzinfo=tzlocal).astimezone(tztodo)
        elif hasattr(vtodo, 'recurrence-id'):
            del vtodo.recurrence_id
        if self.status:
            if not hasattr(vtodo, 'status'):
                vtodo.add('status')
            vtodo.status.value = self.status.upper()
        elif hasattr(vtodo, 'status'):
            del vtodo.status
        if not hasattr(vtodo, 'uid'):
            vtodo.add('uid')
        vtodo.uid.value = self.uuid
        if not hasattr(vtodo, 'sequence'):
            vtodo.add('sequence')
        vtodo.sequence.value = str(self.sequence) or '0'
        if self.categories:
            if not hasattr(vtodo, 'categories'):
                vtodo.add('categories')
            vtodo.categories.value = [x.name for x in self.categories]
        elif hasattr(vtodo, 'categories'):
            del vtodo.categories
        if not hasattr(vtodo, 'class'):
            vtodo.add('class')
            getattr(vtodo, 'class').value = self.classification.upper()
        elif getattr(vtodo, 'class').value.lower() in \
                dict(self.__class__.classification.selection):
            getattr(vtodo, 'class').value = self.classification.upper()
        if self.location:
            if not hasattr(vtodo, 'location'):
                vtodo.add('location')
            vtodo.location.value = self.location.name
        elif hasattr(vtodo, 'location'):
            del vtodo.location

        if self.organizer:
            if not hasattr(vtodo, 'organizer'):
                vtodo.add('organizer')
            vtodo.organizer.value = 'MAILTO:' + self.organizer
        elif hasattr(vtodo, 'organizer'):
            del vtodo.organizer

        vtodo.attendee_list = []
        for attendee in self.attendees:
            vtodo.attendee_list.append(attendee.attendee2attendee())

        if self.rdates:
            vtodo.add('rdate')
            vtodo.rdate.value = []
            for rdate in self.rdates:
                vtodo.rdate.value.append(rdate.date2date())

        if self.exdates:
            vtodo.add('exdate')
            vtodo.exdate.value = []
            for exdate in self.exdates:
                vtodo.exdate.value.append(exdate.date2date())

        if self.rrules:
            for rrule in self.rrules:
                vtodo.add('rrule').value = rrule.rule2rule()

        if self.exrules:
            for exrule in self.exrules:
                vtodo.add('exrule').value = exrule.rule2rule()

        vtodo.valarm_list = []
        for alarm in self.alarms:
            valarm = alarm.alarm2valarm()
            if valarm:
                vtodo.valarm_list.append(valarm)

        for occurence in self.occurences:
            rical = self.todo2ical(occurence)
            ical.vtodo_list.append(rical.vtodo)
        return ical


class TodoCategory(ModelSQL):
    'Todo - Category'
    __name__ = 'calendar.todo-calendar.category'
    todo = fields.Many2One('calendar.todo', 'To-Do', ondelete='CASCADE',
            required=True, select=True)
    category = fields.Many2One('calendar.category', 'Category',
            ondelete='CASCADE', required=True, select=True)


class TodoRDate(DateMixin, ModelSQL, ModelView):
    'Todo Recurrence Date'
    __name__ = 'calendar.todo.rdate'
    _rec_name = 'datetime'
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            select=True, required=True)

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().cursor
        sql_table = cls.__table__()
        # Migration from 1.4: calendar_rdate renamed to calendar_date
        table = TableHandler(cursor, cls, module_name)
        old_column = 'calendar_rdate'
        if table.column_exist(old_column):
            table.column_rename(old_column, 'calendar_date')

        super(TodoRDate, cls).__register__(module_name)

        table = TableHandler(cursor, cls, module_name)

        # Migration from 2.6: Remove inherits calendar.date
        if table.column_exist('calendar_date'):
            date = Table('calendar_date')
            cursor.execute(*sql_table.update(
                    columns=[sql_table.date, sql_table.datetime],
                    values=[date.select(date.date,
                            where=date.id == sql_table.calendar_date),
                        date.select(date.datetime,
                            where=date.id == sql_table.calendar_date)]))
            table.drop_column('calendar_date', True)

    @classmethod
    def create(cls, vlist):
        Todo = Pool().get('calendar.todo')
        towrite = []
        for values in vlist:
            if values.get('todo'):
                # Update write_date of todo
                towrite.append(values['todo'])
        if towrite:
            Todo.write(Todo.browse(towrite), {})
        return super(TodoRDate, cls).create(vlist)

    @classmethod
    def write(cls, *args):
        Todo = Pool().get('calendar.todo')

        actions = iter(args)
        todos = []
        for rdates, values in zip(actions, actions):
            todos += [x.todo for x in rdates]
            if values.get('todo'):
                todos.append(Todo(values['todo']))
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoRDate, cls).write(*args)

    @classmethod
    def delete(cls, todo_rdates):
        pool = Pool()
        Todo = pool.get('calendar.todo')
        todos = [x.todo for x in todo_rdates]
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoRDate, cls).delete(todo_rdates)


class TodoRRule(RRuleMixin, ModelSQL, ModelView):
    'Recurrence Rule'
    __name__ = 'calendar.todo.rrule'
    _rec_name = 'freq'
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            select=True, required=True)

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().cursor
        sql_table = cls.__table__()

        super(TodoRRule, cls).__register__(module_name)

        table = TableHandler(cursor, cls, module_name)

        # Migration from 2.6: Remove inherits calendar.rrule
        if table.column_exist('calendar_rrule'):
            rrule = Table('calendar_rrule')
            for field in (f for f in dir(RRuleMixin)
                    if isinstance(f, fields.Field)):
                cursor.execute(*sql_table.update(
                        columns=[Column(sql_table, field)],
                        values=[rrule.select(Column(rrule, field),
                                where=rrule.id == sql_table.calendar_rrule)]))
            table.drop_column('calendar_rrule', True)

    @classmethod
    def create(cls, vlist):
        Todo = Pool().get('calendar.todo')
        towrite = []
        for values in vlist:
            if values.get('todo'):
                # Update write_date of todo
                towrite.append(values['todo'])
        if towrite:
            Todo.write(Todo.browse(towrite), {})
        return super(TodoRRule, cls).create(vlist)

    @classmethod
    def write(cls, *args):
        Todo = Pool().get('calendar.todo')

        actions = iter(args)
        todos = []
        for todo_rrules, values in zip(actions, actions):
            todos += [x.todo for x in todo_rrules]
            if values.get('todo'):
                todos.append(Todo(values['todo']))
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoRRule, cls).write(*args)

    @classmethod
    def delete(cls, todo_rrules):
        pool = Pool()
        Todo = pool.get('calendar.todo')
        todos = [x.todo for x in todo_rrules]
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoRRule, cls).delete(todo_rrules)


class TodoExDate(TodoRDate):
    'Exception Date'
    __name__ = 'calendar.todo.exdate'
    _table = 'calendar_todo_exdate'  # Needed to override TodoRDate._table


class TodoExRule(TodoRRule):
    'Exception Rule'
    __name__ = 'calendar.todo.exrule'
    _table = 'calendar_todo_exrule'  # Needed to override TodoRRule._table


class TodoAttendee(AttendeeMixin, ModelSQL, ModelView):
    'Attendee'
    __name__ = 'calendar.todo.attendee'
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            required=True, select=True)

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().cursor
        sql_table = cls.__table__()

        super(TodoAttendee, cls).__register__(module_name)

        table = TableHandler(cursor, cls, module_name)

        # Migration from 2.6: Remove inherits calendar.attendee
        if table.column_exist('calendar_attendee'):
            attendee = Table('calendar_attendee')
            cursor.execute(*sql_table.update(
                    columns=[sql_table.email, sql_table.status],
                    values=[attendee.select(attendee.email,
                            where=attendee.id == sql_table.calendar_attendee),
                        attendee.select(attendee.status,
                            where=(
                                attendee.id == sql_table.calendar_attendee))]))
            table.drop_column('calendar_attendee', True)

    @classmethod
    def create(cls, vlist):
        Todo = Pool().get('calendar.todo')

        towrite = []
        for values in vlist:
            if values.get('todo'):
                # Update write_date of todo
                towrite.append(values['todo'])
        if towrite:
            Todo.write(Todo.browse(towrite), {})
        attendees = super(TodoAttendee, cls).create(vlist)
        for attendee in attendees:
            todo = attendee.todo
            if (todo.calendar.owner
                    and (todo.organizer == todo.calendar.owner.email
                        or (todo.parent
                            and todo.parent.organizer
                            == todo.parent.calendar.owner.email))):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.email != todo.organizer]
                else:
                    attendee_emails = [x.email for x in todo.parent.attendees
                            if x.email != todo.parent.organizer]
                if attendee_emails:
                    with Transaction().set_user(0):
                        todos = Todo.search([
                            ('uuid', '=', todo.uuid),
                            ('calendar.owner.email', 'in', attendee_emails),
                            ('id', '!=', todo.id),
                            ('recurrence', '=', todo.recurrence),
                            ])
                        for todo in todos:
                            cls.copy([attendee], default={
                                'todo': todo.id,
                                })
        return attendees

    @classmethod
    def write(cls, *args):
        Todo = Pool().get('calendar.todo')

        actions = iter(args)
        args = []
        todos = []
        for todo_attendees, values in zip(actions, actions):
            todos += [x.todo.id for x in todo_attendees]
            if values.get('todo'):
                todos.append(Todo(values['todo']))
            if 'email' in values:
                values = values.copy()
                del values['email']
            args.extend((todo_attendees, values))

        if todos:
            # Update write_date of todo
            Todo.write(todos, {})

        super(TodoAttendee, cls).write(*args)

        for todo_attendee in sum(args[::2], []):
            todo = todo_attendee.todo
            if (todo.calendar.owner
                    and (todo.organizer == todo.calendar.owner.email
                        or (todo.parent
                            and todo.parent.organizer
                            == todo.calendar.owner.email))):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.email != todo.organizer]
                else:
                    attendee_emails = [x.email for x in todo.parent.attendees
                            if x.email != todo.parent.organizer]
                if attendee_emails:
                    with Transaction().set_user(0):
                        attendees2 = cls.search([
                                ('todo.uuid', '=', todo.uuid),
                                ('todo.calendar.owner.email', 'in',
                                    attendee_emails),
                                ('id', '!=', todo_attendee.id),
                                ('todo.recurrence', '=', todo.recurrence),
                                ('email', '=', todo_attendee.email),
                                ])
                        cls.write(attendees2, todo_attendee._attendee2update())

    @classmethod
    def delete(cls, todo_attendees):
        pool = Pool()
        Todo = pool.get('calendar.todo')

        todos = [x.todo for x in todo_attendees]
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})

        for attendee in todo_attendees:
            todo = attendee.todo
            if (todo.calendar.owner
                    and (todo.organizer == todo.calendar.owner.email
                        or (todo.parent
                            and todo.parent.organizer
                            == todo.calendar.owner.email))):
                if todo.organizer == todo.calendar.owner.email:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.email != todo.organizer]
                else:
                    attendee_emails = [x.email for x in todo.attendees
                            if x.email != todo.parent.organizer]
                if attendee_emails:
                    with Transaction().set_user(0):
                        attendees = cls.search([
                            ('todo.uuid', '=', todo.uuid),
                            ('todo.calendar.owner.email', 'in',
                                attendee_emails),
                            ('id', '!=', attendee.id),
                            ('todo.recurrence', '=', todo.recurrence),
                            ('email', '=', attendee.email),
                            ])
                        cls.delete(attendees)
            elif (todo.calendar.organizer
                    and ((todo.organizer
                            or (todo.parent and todo.parent.organizer))
                        and attendee.email == todo.calendar.owner.email)):
                if todo.organizer:
                    organizer = todo.organizer
                else:
                    organizer = todo.parent.organizer
                with Transaction().set_user(0):
                    attendees = cls.search([
                        ('todo.uuid', '=', todo.uuid),
                        ('todo.calendar.owner.email', '=', organizer),
                        ('id', '!=', attendee.id),
                        ('todo.recurrence', '=', todo.recurrence),
                        ('email', '=', attendee.email),
                        ])
                    if attendees:
                        cls.write(attendees, {
                            'status': 'declined',
                            })
        super(TodoAttendee, cls).delete(todo_attendees)


class TodoAlarm(AlarmMixin, ModelSQL, ModelView):
    'Alarm'
    __name__ = 'calendar.todo.alarm'
    todo = fields.Many2One('calendar.todo', 'Todo', ondelete='CASCADE',
            required=True, select=True)

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        cursor = Transaction().cursor
        sql_table = cls.__table__()

        super(TodoAlarm, cls).__register__(module_name)

        table = TableHandler(cursor, cls, module_name)

        # Migration from 2.6: Remove inherits calendar.alarm
        if table.column_exist('calendar_alarm'):
            alarm = Table('calendar_alarm')
            cursor.execute(*sql_table.update(
                    columns=[sql_table.valarm],
                    values=[alarm.select(alarm.valarm,
                            where=alarm.id == sql_table.calendar_alarm)]))
            table.drop_column('calendar_alarm', True)

    @classmethod
    def create(cls, vlist):
        Todo = Pool().get('calendar.todo')
        towrite = []
        for values in vlist:
            if values.get('todo'):
                # Update write_date of todo
                towrite.append(values['todo'])
        if towrite:
            Todo.write(Todo.browse(towrite), {})
        return super(TodoAlarm, cls).create(vlist)

    @classmethod
    def write(cls, *args):
        Todo = Pool().get('calendar.todo')

        actions = iter(args)
        todos = []
        for alarms, values in zip(actions, actions):
            todos += [x.todo for x in alarms]
            if values.get('todo'):
                todos.append(Todo(values['todo']))
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoAlarm, cls).write(*args)

    @classmethod
    def delete(cls, todo_alarms):
        pool = Pool()
        Todo = pool.get('calendar.todo')
        todos = [x.todo for x in todo_alarms]
        if todos:
            # Update write_date of todo
            Todo.write(todos, {})
        super(TodoAlarm, cls).delete(todo_alarms)
