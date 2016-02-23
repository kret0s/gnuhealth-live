#!/usr/bin/env python
# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from argparse import ArgumentParser
from urlparse import urlparse
import unittest
import sys
import datetime

from dateutil.relativedelta import relativedelta
import caldav
import vobject
from proteus import config
from trytond.modules.calendar.tests.scenario_calendar import (
    install_module, configure_user, create_calendar)


class TestCase(unittest.TestCase):

    def setUp(self):
        self.client = caldav.DAVClient(URL)
        self.principal = caldav.Principal(self.client, URL)
        self.calendar, = [x for x in self.principal.calendars()
            if x.url.path.endswith(user)]

    def test0010create_event_external(self):
        'Create event with external attendee'
        ical = vobject.iCalendar()
        vevent = ical.add('vevent')
        vevent.add('summary')
        vevent.summary.value = 'Test event with external attendee'
        vevent.add('dtstart')
        vevent.dtstart.value = datetime.datetime.now() + relativedelta(days=10)
        vevent.add('dtend')
        vevent.dtend.value = datetime.datetime.now() + relativedelta(days=10,
            hours=4)
        vevent.add('organizer')
        vevent.organizer.value = 'admin@example.com'
        attendee = vobject.base.ContentLine('ATTENDEE', [], '')
        attendee.partstat_param = 'TENTATIVE'
        attendee.value = 'MAILTO:bar@example.com'
        vevent.attendee_list = [attendee]
        caldav.Event(self.client, data=ical.serialize(),
            parent=self.calendar).save()

    def test0020create_event_ext_int(self):
        'Create event with external and internal attendees'
        ical = vobject.iCalendar()
        vevent = ical.add('vevent')
        vevent.add('summary')
        vevent.summary.value = 'Test event with ext/int attendees'
        vevent.add('dtstart')
        vevent.dtstart.value = datetime.datetime.now() + relativedelta(days=5)
        vevent.add('dtend')
        vevent.dtend.value = datetime.datetime.now() + relativedelta(days=5,
            hours=8)
        vevent.add('organizer')
        vevent.organizer.value = 'admin@example.com'
        attendees = []
        for email in ('foo@example', 'bar@example.com'):
            attendee = vobject.base.ContentLine('ATTENDEE', [], '')
            attendee.partstat_param = 'TENTATIVE'
            attendee.value = 'MAILTO:%s' % email
            attendees.append(attendee)
        vevent.attendee_list = attendees
        caldav.Event(self.client, data=ical.serialize(),
            parent=self.calendar).save()

if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--xmlrpc', dest='xmlrpc', metavar='URL',
        help='use trytond XML-RPC at URL')
    parser.add_argument('--url', dest='url', metavar='URL',
        help='use calendar at URL')
    options = parser.parse_args()
    config = config.set_xmlrpc(options.xmlrpc)
    xmlrpc_user = urlparse(options.xmlrpc).username
    user = urlparse(options.url).username
    assert xmlrpc_user == user
    assert user != 'foo'
    install_module('calendar_scheduling', config)
    configure_user(user, config)
    configure_user('foo', config)
    create_calendar(user, user, config)
    create_calendar('foo', user, config)
    URL = options.url
    unittest.main(argv=sys.argv[:1])
