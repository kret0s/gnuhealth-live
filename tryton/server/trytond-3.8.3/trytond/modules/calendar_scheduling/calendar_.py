# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
import logging

import dateutil.tz

from trytond.model import fields
from trytond.tools import get_smtp_server
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta

__all__ = ['Event', 'EventAttendee']
__metaclass__ = PoolMeta
tzlocal = dateutil.tz.tzlocal()

logger = logging.getLogger(__name__)


class Event:
    __name__ = 'calendar.event'
    organizer_schedule_status = fields.Selection([
            ('', ''),
            ('1.0', '1.0'),
            ('1.1', '1.1'),
            ('1.2', '1.2'),
            ('3.7', '3.7'),
            ('3.8', '3.8'),
            ('5.1', '5.1'),
            ('5.2', '5.2'),
            ('5.3', '5.3'),
            ], 'Schedule Status')
    organizer_schedule_agent = fields.Selection([
            ('', ''),
            ('NONE', 'None'),
            ('SERVER', 'Server'),
            ('CLIENT', 'Client'),
            ], 'Schedule Agent')

    @staticmethod
    def default_organizer_schedule_agent():
        return 'SERVER'

    @classmethod
    def __setup__(cls):
        super(Event, cls).__setup__()
        cls._error_messages.update({
            'new_subject': 'Invitation: %s @ %s',
            'new_body': 'You have been invited to the following event.\n\n',
            'update_subject': 'Updated Invitation: %s @ %s',
            'update_body': 'This event has been changed.\n\n',
            'cancel_subject': 'Cancelled Event: %s @ %s',
            'cancel_body': 'This event has been canceled.\n\n',
            'no_subject': "(No Subject)",
            'separator': ':',
            'bullet': '    * ',
            'when': 'When',
            })

    @classmethod
    def ical2values(cls, event_id, ical, calendar_id, vevent=None):
        res = super(Event, cls).ical2values(event_id, ical, calendar_id,
            vevent=vevent)

        if not vevent:
            vevent = ical.vevent

        if not hasattr(vevent, 'organizer'):
            return res

        for key in ('status', 'agent'):
            field = 'organizer_schedule_' + key
            param = 'SCHEDULE-' + key.upper()
            selection = dict(getattr(cls, field).selection)
            if (param in vevent.organizer.params
                    and vevent.organizer.params[param][0] in selection):
                res[field] = vevent.organizer.params[param][0]

        return res

    def event2ical(self):
        """
        Override default event2ical to add schedule-status and
        schedule-agent properties

        If key skip_schedule_agent is present and associated to True, will
        prevent the schedule-status to be add to the organiser property. This
        is needed when one want to generate an ical that will be used for
        scheduling message.
        """

        ical = super(Event, self).event2ical()
        vevent = ical.vevent

        if self.organizer_schedule_status:
            if not hasattr(vevent, 'organizer'):
                vevent.add('organizer')
            vevent.organizer.params['SCHEDULE-STATUS'] = \
                (self.organizer_schedule_status,)

        if Transaction().context.get('skip_schedule_agent'):
            if (hasattr(vevent, 'organizer')
                    and hasattr(vevent.organizer, 'schedule_agent_param')):
                del vevent.organizer.schedule_agent_param
            return ical

        if self.organizer_schedule_agent:
            if not hasattr(vevent, 'organizer'):
                vevent.add('organizer')
            vevent.organizer.params['SCHEDULE-AGENT'] = \
                self.organizer_schedule_agent

        return ical

    def subject_body(self, type, owner):
        Lang = Pool().get('ir.lang')

        if not owner:
            return "", ""
        lang = owner.language
        if not lang:
            lang, = Lang.search([
                    ('code', '=', 'en_US'),
                    ], limit=1)

        with Transaction().set_context(language=lang.code):
            summary = self.summary
            if not summary:
                summary = self.raise_user_error('no_subject',
                        raise_exception=False)

        if self.timezone:
            tzevent = dateutil.tz.gettz(self.timezone)
        else:
            tzevent = tzlocal
        dtstart = self.dtstart.replace(tzinfo=tzlocal).astimezone(tzevent)
        if self.dtend:
            dtend = self.dtend.replace(tzinfo=tzlocal).astimezone(tzevent)
        else:
            dtend = None

        date = Lang.strftime(dtstart, lang.code, lang.date)
        if not self.all_day:
            date += ' ' + Lang.strftime(dtstart, lang.code, '%H:%M')
            if self.dtend:
                date += ' -'
                if self.dtstart.date() != self.dtend.date():
                    date += ' ' + Lang.strftime(dtend, lang.code,
                        lang.date)
                date += ' ' + Lang.strftime(dtend, lang.code, '%H:%M')
        else:
            if self.dtend and self.dtstart.date() != self.dtend.date():
                date += ' - ' + Lang.strftime(dtend, lang.code, lang.date)
        if self.timezone:
            date += ' ' + self.timezone

        with Transaction().set_context(language=lang.code):
            subject = self.raise_user_error(type + '_subject',
                    (summary, date), raise_exception=False)
            body = self.raise_user_error(type + '_body', (summary, ),
                    raise_exception=False)
            separator = self.raise_user_error('separator',
                    raise_exception=False)
            bullet = self.raise_user_error('bullet', raise_exception=False)

        fields_names = ['summary', 'dtstart', 'location', 'attendees']
        if type == 'cancel':
            fields_names.remove('attendees')
        with Transaction().set_context(language=lang.code):
            fields = self.fields_get(fields_names=fields_names)
            fields['dtstart']['string'] = self.raise_user_error('when',
                    raise_exception=False)
        for field in fields_names:
            if field == 'attendees':
                if lang.direction == 'ltr':
                    body += fields['attendees']['string'] + separator + '\n'
                    body += bullet + owner.email + '\n'
                    for attendee in self.attendees:
                        body += bullet + attendee.email + '\n'
                else:
                    body += separator + fields['attendees']['string'] + '\n'
                    body += owner.email + bullet + '\n'
                    for attendee in self.attendees:
                        body += attendee.email + bullet + '\n'
            elif getattr(self, field):
                if field == 'summary':
                    value = summary
                elif field == 'dtstart':
                    value = date
                elif field == 'location':
                    value = self.location.name
                else:
                    value = getattr(self, field)
                if lang.direction == 'ltr':
                    body += fields[field]['string'] + separator + ' ' \
                        + value + '\n'
                else:
                    body += value + ' ' + separator \
                        + fields[field]['string'] + '\n'
        return subject, body

    @staticmethod
    def create_msg(from_addr, to_addrs, subject, body, ical=None):

        if not to_addrs:
            return None

        msg = MIMEMultipart()
        msg['To'] = ', '.join(to_addrs)
        msg['From'] = from_addr
        msg['Subject'] = subject

        inner = MIMEMultipart('alternative')

        msg_body = MIMEBase('text', 'plain')
        msg_body.set_payload(body.encode('UTF-8'), 'UTF-8')
        inner.attach(msg_body)

        attachment = MIMEBase('text', 'calendar',
            method=ical.method.value)
        attachment.set_payload(ical.serialize(), 'UTF-8')
        inner.attach(attachment)

        msg.attach(inner)

        attachment = MIMEBase('application', 'ics')
        attachment.set_payload(ical.serialize(), 'UTF-8')
        attachment.add_header('Content-Disposition', 'attachment',
                filename='invite.ics', name='invite.ics')

        msg.attach(attachment)

        return msg

    def send_msg(self, from_addr, to_addrs, msg, type):
        '''
        Send message and return the list of email addresses sent
        '''
        User = Pool().get('res.user')

        if not to_addrs:
            return to_addrs
        to_addrs = list(set(to_addrs))

        users = User.search([
                ('email', 'in', to_addrs),
                ])
        for user in users:
            if not getattr(user, 'calendar_email_notification_' + type):
                to_addrs.remove(user.email)

        success = False
        try:
            server = get_smtp_server()
            server.sendmail(from_addr, to_addrs, msg.as_string())
            server.quit()
            success = to_addrs
        except Exception:
            logger.error(
                'Unable to deliver scheduling mail for %s', self,
                exc_info=True)
        return success

    def attendees_to_notify(self):
        if not self.calendar.owner:
            return [], None
        attendees = self.attendees
        organizer = self.organizer
        owner = self.calendar.owner
        if self.parent:
            if not attendees:
                attendees = self.parent.attendees
                organizer = self.parent.organizer
                owner = self.parent.calendar.owner
            elif not organizer:
                organizer = self.parent.organizer
                owner = self.parent.calendar.owner

        if organizer != owner.email:
            return [], None

        to_notify = []
        for attendee in attendees:
            if attendee.email == organizer:
                continue
            if (attendee.schedule_agent
                    and attendee.schedule_agent != 'SERVER'):
                continue
            to_notify.append(attendee)

        return to_notify, owner

    @classmethod
    def create(cls, vlist):
        Attendee = Pool().get('calendar.event.attendee')
        events = super(Event, cls).create(vlist)

        if Transaction().user == 0:
            # user is 0 means create is triggered by another one
            return events

        for event in events:
            to_notify, owner = event.attendees_to_notify()
            if not to_notify:
                continue

            with Transaction().set_context(skip_schedule_agent=True):
                ical = event.event2ical()
            ical.add('method')
            ical.method.value = 'REQUEST'

            attendee_emails = [a.email for a in to_notify]

            subject, body = event.subject_body('new', owner)
            msg = cls.create_msg(owner.email, attendee_emails, subject, body,
                ical)
            sent = event.send_msg(owner.email, attendee_emails, msg, 'new')

            vals = {'status': 'needs-action'}
            if sent:
                vals['schedule_status'] = '1.1'  # successfully sent
            else:
                vals['schedule_status'] = '5.1'  # could not complete delivery
            Attendee.write(to_notify, vals)

        return events

    @classmethod
    def write(cls, *args):
        Attendee = Pool().get('calendar.event.attendee')

        if Transaction().user == 0:
            # user is 0 means write is triggered by another one
            super(Event, cls).write(*args)
            return

        actions = iter(args)
        events_edited = set()
        for events, values in zip(actions, actions):
            for k in values:
                if k != 'attendees':
                    events_edited.update(events)
                    break

            # store old attendee info
            event2former_emails = {}
            former_organiser_mail = {}
            former_organiser_lang = {}
            for event in events:
                to_notify, owner = event.attendees_to_notify()
                event2former_emails[event.id] = [a.email for a in to_notify]
                former_organiser_mail[event.id] = owner and owner.email
                former_organiser_lang[event.id] = owner and owner.language \
                    and owner.language.code

        super(Event, cls).write(*args)

        for event in sum(args[::2], []):
            current_attendees, owner = event.attendees_to_notify()
            owner_email = owner and owner.email
            current_emails = [a.email for a in current_attendees]
            former_emails = event2former_emails.get(event.id, [])
            missing_mails = filter(lambda mail: mail not in current_emails,
                    former_emails)

            if missing_mails:
                with Transaction().set_context(skip_schedule_agent=True):
                    ical = event.event2ical()
                ical.add('method')
                ical.method.value = 'CANCEL'

                subject, body = event.subject_body('cancel', owner)
                msg = cls.create_msg(former_organiser_mail[event.id],
                    missing_mails, subject, body, ical)
                sent = event.send_msg(former_organiser_mail[event.id],
                    missing_mails, msg, 'cancel')

            new_attendees = filter(lambda a: a.email not in former_emails,
                current_attendees)
            old_attendees = filter(lambda a: a.email in former_emails,
                current_attendees)
            with Transaction().set_context(skip_schedule_agent=True):
                ical = event.event2ical()
            if not hasattr(ical, 'method'):
                ical.add('method')

            sent_succes = []
            sent_fail = []
            if event in events_edited:
                if event.status == 'cancelled':
                    ical.method.value = 'CANCEL'
                    # send cancel to old attendee
                    subject, body = event.subject_body('cancel', owner)
                    msg = cls.create_msg(owner_email,
                        [a.email for a in old_attendees],
                        subject, body, ical)
                    sent = event.send_msg(owner_email,
                        [a.email for a in old_attendees],
                        msg, 'cancel')
                    if sent:
                        sent_succes += old_attendees
                    else:
                        sent_fail += old_attendees

                else:
                    ical.method.value = 'REQUEST'
                    # send update to old attendees
                    subject, body = event.subject_body('update', owner)
                    msg = cls.create_msg(owner_email,
                        [a.email for a in old_attendees],
                        subject, body, ical)
                    sent = event.send_msg(owner_email,
                        [a.email for a in old_attendees],
                        msg, 'update')
                    if sent:
                        sent_succes += old_attendees
                    else:
                        sent_fail += old_attendees
                    # send new to new attendees
                    subject, body = event.subject_body('new', owner)
                    msg = cls.create_msg(owner_email,
                        [a.email for a in new_attendees],
                        subject, body, ical)
                    sent = event.send_msg(owner_email,
                        [a.email for a in new_attendees],
                        msg, 'new')
                    if sent:
                        sent_succes += new_attendees
                    else:
                        sent_fail += new_attendees

            else:
                if event.status != 'cancelled':
                    ical.method.value = 'REQUEST'
                    # send new to new attendees
                    subject, body = event.subject_body('new', owner)
                    msg = cls.create_msg(owner_email,
                        [a.email for a in new_attendees],
                        subject, body, ical)
                    sent = event.send_msg(owner_email,
                        [a.email for a in new_attendees],
                        msg, 'new')
                    if sent:
                        sent_succes += new_attendees
                    else:
                        sent_fail += new_attendees

                vals = {'status': 'needs-action'}
                vals['schedule_status'] = '1.1'  # successfully sent
                if sent_succes:
                    Attendee.write(sent_succes, vals)
                vals['schedule_status'] = '5.1'  # could not complete delivery
                if sent_fail:
                    Attendee.write(sent_fail, vals)

    @classmethod
    def delete(cls, events):
        if Transaction().user == 0:
            # user is 0 means the deletion is triggered by another one
            super(Event, cls).delete(events)
            return

        send_list = []
        for event in events:
            if event.status == 'cancelled':
                continue
            to_notify, owner = event.attendees_to_notify()
            if not to_notify:
                continue

            with Transaction().set_context(skip_schedule_agent=True):
                ical = event.event2ical()
            ical.add('method')
            ical.method.value = 'CANCEL'

            attendee_emails = [a.email for a in to_notify]
            subject, body = event.subject_body('cancel', owner)
            msg = cls.create_msg(owner.email, attendee_emails, subject, body,
                ical)

            send_list.append((owner.email, attendee_emails, msg, event))

        super(Event, cls).delete(events)
        for args in send_list:
            owner_email, attendee_emails, msg, event = args
            event.send_msg(owner_email, attendee_emails, msg, 'cancel')


class AttendeeMixin:
    schedule_status = fields.Selection([
            ('', ''),
            ('1.0', '1.0'),
            ('1.1', '1.1'),
            ('1.2', '1.2'),
            ('3.7', '3.7'),
            ('3.8', '3.8'),
            ('5.1', '5.1'),
            ('5.2', '5.2'),
            ('5.3', '5.3'),
            ], 'Schedule Status')
    schedule_agent = fields.Selection([
            ('', ''),
            ('NONE', 'None'),
            ('SERVER', 'Server'),
            ('CLIENT', 'Client'),
            ], 'Schedule Agent')

    @staticmethod
    def default_schedule_agent():
        return 'SERVER'

    @classmethod
    def attendee2values(cls, attendee):
        # Those params don't need to be stored
        for param in ['received_dtstamp_param', 'received_sequence_param']:
            if hasattr(attendee, param):
                delattr(attendee, param)
        values = super(AttendeeMixin, cls).attendee2values(attendee)
        if hasattr(attendee, 'schedule_status'):
            if attendee.schedule_status in dict(
                    cls.schedule_status.selection):
                values['schedule_status'] = attendee.schedule_status
        if hasattr(attendee, 'schedule_agent'):
            if attendee.schedule_agent in dict(cls.schedule_agent.selection):
                values['schedule_agent'] = attendee.schedule_agent
        return values

    def attendee2attendee(self):
        attendee = super(AttendeeMixin, self).attendee2attendee()

        if self.schedule_status:
            if hasattr(attendee, 'schedule_status_param'):
                if attendee.schedule_status_param in dict(
                        self.__class__.schedule_status.selection):
                    attendee.schedule_status_param = self.schedule_status
            else:
                attendee.schedule_status_param = self.schedule_status
        elif hasattr(attendee, 'schedule_status_param'):
            if attendee.schedule_status_param in dict(
                    self.__class__.schedule_status.selection):
                del attendee.schedule_status_param

        if Transaction().context.get('skip_schedule_agent'):
            if hasattr(attendee, 'schedule_agent_param'):
                del attendee.schedule_agent_param
            return attendee

        if self.schedule_agent:
            if hasattr(attendee, 'schedule_agent_param'):
                if attendee.schedule_agent_param in dict(
                        self.__class__.schedule_agent.selection):
                    attendee.schedule_agent_param = self.schedule_agent
            else:
                attendee.schedule_agent_param = self.schedule_agent
        elif hasattr(attendee, 'schedule_agent_param'):
            if attendee.schedule_agent_param in dict(
                    self.__class__.schedule_agent.selection):
                del attendee.schedule_agent_param

        return attendee


class EventAttendee(AttendeeMixin, object):
    __metaclass__ = PoolMeta
    __name__ = 'calendar.event.attendee'

    @classmethod
    def __setup__(cls):
        super(EventAttendee, cls).__setup__()
        cls._error_messages.update({
                'subject': '%s: %s @ %s',
                'body': ('%s (%s) changed his/her participation status '
                    'to: %s\n\n'),
                'accepted_body': '%s (%s) has accepted this invitation:\n\n',
                'declined_body': '%s (%s) has declined this invitation:\n\n',
                'no_subject': "(No Subject)",
                'separator': ':',
                'bullet': '    * ',
                'when': 'When',
                })

    def subject_body(self, status, owner):
        pool = Pool()
        Lang = pool.get('ir.lang')
        Event = pool.get('calendar.event')
        event = self.event

        if not (event and owner):
            return "", ""
        lang = owner.language
        if not lang:
            lang, = Lang.search([
                    ('code', '=', 'en_US'),
                    ], limit=1)

        summary = event.summary
        if not summary:
            with Transaction().set_context(language=lang.code):
                summary = self.raise_user_error('no_subject',
                        raise_exception=False)

        if event.timezone:
            tzevent = dateutil.tz.gettz(event.timezone)
        else:
            tzevent = tzlocal
        dtstart = event.dtstart.replace(tzinfo=tzlocal).astimezone(tzevent)
        if event.dtend:
            dtend = event.dtend.replace(tzinfo=tzlocal).astimezone(tzevent)
        else:
            dtend = None

        date = Lang.strftime(dtstart, lang.code, lang.date)
        if not event.all_day:
            date += ' ' + Lang.strftime(dtstart, lang.code, '%H:%M')
            if event.dtend:
                date += ' -'
                if event.dtstart.date() != event.dtend.date():
                    date += ' ' + Lang.strftime(dtend, lang.code,
                        lang.date)
                date += ' ' + Lang.strftime(dtend, lang.code, '%H:%M')
        else:
            if event.dtend and event.dtstart.date() != event.dtend.date():
                date += ' - ' + Lang.strftime(dtend, lang.code,
                    lang.date)
        if event.timezone:
            date += ' ' + event.timezone

        status_string = status
        fields_names = ['status']
        with Transaction().set_context(language=lang.code):
            fields = self.fields_get(fields_names=fields_names)
        for k, v in fields['status']['selection']:
            if k == status:
                status_string = v

        with Transaction().set_context(language=lang.code):
            subject = self.raise_user_error('subject', (status, summary, date),
                    raise_exception=False)

            if status + '_body' in self._error_messages:
                body = self.raise_user_error(status + '_body',
                        (owner.name, owner.email), raise_exception=False)
            else:
                body = self.raise_user_error('body',
                        (owner.name, owner.email, status_string),
                        raise_exception=False)

            separator = self.raise_user_error('separator',
                    raise_exception=False)
            bullet = self.raise_user_error('bullet', raise_exception=False)

            fields_names = ['summary', 'dtstart', 'location', 'attendees']
            fields = Event.fields_get(fields_names=fields_names)
            fields['dtstart']['string'] = self.raise_user_error('when',
                    raise_exception=False)
        for field in fields_names:
            if field == 'attendees':
                organizer = event.organizer or event.parent.organizer
                if lang.direction == 'ltr':
                    body += fields['attendees']['string'] + separator + '\n'
                    if organizer:
                        body += bullet + organizer + '\n'
                    for attendee in event.attendees:
                        body += bullet + attendee.email + '\n'
                else:
                    body += separator + fields['attendees']['string'] + '\n'
                    if organizer:
                        body += owner.email + bullet + '\n'
                    for attendee in event.attendees:
                        body += attendee.email + bullet + '\n'
            elif getattr(event, field):
                if field == 'summary':
                    value = summary
                elif field == 'dtstart':
                    value = date
                elif field == 'location':
                    value = event.location.name
                else:
                    value = event[field]
                if lang.direction == 'ltr':
                    body += fields[field]['string'] + separator + ' ' \
                        + value + '\n'
                else:
                    body += value + ' ' + separator \
                        + fields[field]['string'] + '\n'
        return subject, body

    @staticmethod
    def create_msg(from_addr, to_addr, subject, body, ical=None):

        if not to_addr:
            return None

        msg = MIMEMultipart()
        msg['To'] = to_addr
        msg['From'] = from_addr
        msg['Subject'] = subject

        inner = MIMEMultipart('alternative')

        msg_body = MIMEBase('text', 'plain')
        msg_body.set_payload(body.encode('UTF-8'), 'UTF-8')
        inner.attach(msg_body)

        attachment = MIMEBase('text', 'calendar',
            method=ical.method.value)
        attachment.set_payload(ical.serialize(), 'UTF-8')
        inner.attach(attachment)

        msg.attach(inner)
        attachment = MIMEBase('application', 'ics')
        attachment.set_payload(ical.serialize(), 'UTF-8')
        attachment.add_header('Content-Disposition', 'attachment',
                filename='invite.ics', name='invite.ics')

        msg.attach(attachment)

        return msg

    def send_msg(self, from_addr, to_addr, msg):
        '''
        Send message and return True if the mail has been sent
        '''
        success = False
        try:
            server = get_smtp_server()
            server.sendmail(from_addr, to_addr, msg.as_string())
            server.quit()
            success = True
        except Exception:
            logger.error(
                'Unable to deliver reply mail for %s', self, exc_info=True)
        return success

    def organiser_to_notify(self):
        event = self.event
        organizer = event.organizer or event.parent and event.parent.organizer
        if not organizer:
            return None
        if event.organizer_schedule_agent \
                and event.organizer_schedule_agent != 'SERVER':
            return None
        if organizer == event.calendar.owner.email:
            return None
        if self.email != event.calendar.owner.email:
            return None

        return organizer

    @classmethod
    def write(cls, *args):
        Event = Pool().get('calendar.event')

        if Transaction().user == 0:
            # user is 0 means write is triggered by another one
            super(EventAttendee, cls).write(*args)
            return

        actions = iter(args)
        status_attendees = []
        att2status = {}
        for attendees, values in zip(actions, actions):
            if 'status' in values:
                status_attendees += attendees
                for attendee in attendees:
                    att2status[attendee.id] = attendee.status

        super(EventAttendee, cls).write(*args)

        for attendee in status_attendees:
            owner = attendee.event.calendar.owner
            if not owner or not owner.calendar_email_notification_partstat:
                continue
            organizer = attendee.organiser_to_notify()
            if not organizer:
                continue

            old, new = (att2status.get(attendee.id) or 'needs-action',
                        attendee.status or 'needs-action')

            if old == new:
                continue

            with Transaction().set_context(skip_schedule_agent=True):
                ical = attendee.event.event2ical()
                # Only the current attendee is needed
                ical.vevent.attendee_list = [attendee.attendee2attendee()]
            if not hasattr(ical, 'method'):
                ical.add('method')
            ical.method.value = 'REPLY'

            subject, body = attendee.subject_body(new, owner)
            msg = cls.create_msg(owner.email, organizer, subject, body, ical)

            sent = attendee.send_msg(owner.email, organizer, msg)

            vals = {'organizer_schedule_status': sent and '1.1' or '5.1'}
            Event.write([attendee.event], vals)

    @classmethod
    def delete(cls, attendees):
        Event = Pool().get('calendar.event')

        if Transaction().user == 0:
            # user is 0 means the deletion is triggered by another one
            super(EventAttendee, cls).delete(attendees)
            return

        send_list = []
        for attendee in attendees:
            owner = attendee.event.calendar.owner

            if attendee.status == 'declined':
                continue
            if not owner or not owner.calendar_email_notification_partstat:
                continue
            organizer = attendee.organiser_to_notify()
            if not organizer:
                continue

            with Transaction().set_context(skip_schedule_agent=True):
                ical = attendee.event.event2ical()
                # Only the current attendee is needed
                ical.vevent.attendee_list = [attendee.attendee2attendee()]
            if not hasattr(ical, 'method'):
                ical.add('method')
            ical.method.value = 'REPLY'

            subject, body = attendee.subject_body('declined', owner)
            msg = cls.create_msg(owner.email, organizer, subject, body, ical)

            send_list.append((owner.email, organizer, msg, attendee))

        super(EventAttendee, cls).delete(attendees)
        for args in send_list:
            owner_email, organizer, msg, attendee = args
            sent = attendee.send_msg(owner_email, organizer, msg)
            vals = {'organizer_schedule_status': sent and '1.1' or '5.1'}
            Event.write([attendee.event], vals)

    @classmethod
    def create(cls, vlist):
        Event = Pool().get('calendar.event')

        attendees = super(EventAttendee, cls).create(vlist)
        if Transaction().user == 0:
            # user is 0 means create is triggered by another one
            return attendees

        for attendee in attendees:
            owner = attendee.event.calendar.owner

            if ((not attendee.status)
                    or attendee.status in ('', 'needs-action')):
                continue
            if not owner or not owner.calendar_email_notification_partstat:
                continue
            organizer = attendee.organiser_to_notify()
            if not organizer:
                continue

            with Transaction().set_context(skip_schedule_agent=True):
                ical = attendee.event.event2ical()
                # Only the current attendee is needed
                ical.vevent.attendee_list = [attendee.attendee2attendee()]
            if not hasattr(ical, 'method'):
                ical.add('method')
            ical.method.value = 'REPLY'

            subject, body = attendee.subject_body(attendee.status, owner)
            msg = cls.create_msg(owner.email, organizer, subject, body, ical)

            sent = attendee.send_msg(owner.email, organizer, msg)

            vals = {'organizer_schedule_status': sent and '1.1' or '5.1'}
            Event.write([attendee.event], vals)

        return attendees
