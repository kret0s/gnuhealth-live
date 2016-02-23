# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.model import fields
from trytond.pool import PoolMeta

__all__ = ['User']
__metaclass__ = PoolMeta


class User:
    __name__ = 'res.user'
    calendar_email_notification_new = fields.Boolean(
            'New invitations')
    calendar_email_notification_update = fields.Boolean(
            'Changed invitations')
    calendar_email_notification_cancel = fields.Boolean(
            'Cancelled invitations')
    calendar_email_notification_partstat = fields.Boolean(
            'Invitation Replies')

    @staticmethod
    def default_calendar_email_notification_new():
        return True

    @staticmethod
    def default_calendar_email_notification_update():
        return True

    @staticmethod
    def default_calendar_email_notification_cancel():
        return True

    @staticmethod
    def default_calendar_email_notification_partstat():
        return True

    @classmethod
    def __setup__(cls):
        super(User, cls).__setup__()
        cls._preferences_fields += [
            'calendar_email_notification_new',
            'calendar_email_notification_update',
            'calendar_email_notification_cancel',
            'calendar_email_notification_partstat',
            ]
