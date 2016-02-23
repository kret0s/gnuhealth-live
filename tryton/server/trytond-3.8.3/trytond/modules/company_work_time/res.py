# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.pool import PoolMeta


__all__ = ['User']
__metaclass__ = PoolMeta


class User:
    __name__ = 'res.user'

    @classmethod
    def _get_preferences(cls, user, context_only=False):
        res = super(User, cls)._get_preferences(user,
            context_only=context_only)
        if user.company:
            res['company_work_time'] = {
                'Y': user.company.hours_per_work_year * 60 * 60,
                'M': user.company.hours_per_work_month * 60 * 60,
                'w': user.company.hours_per_work_week * 60 * 60,
                'd': user.company.hours_per_work_day * 60 * 60,
                'h': 60 * 60,
                'm': 60,
                's': 1,
            }
        return res
