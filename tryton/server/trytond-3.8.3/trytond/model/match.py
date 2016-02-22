# This file is part of Tryton.  The COPYRIGHT file at the toplevel of this
# repository contains the full copyright notices and license terms.


class MatchMixin(object):

    def match(self, pattern):
        '''Match on pattern
        pattern is a dictionary with model field as key
        and matching value as value'''
        for field, pattern_value in pattern.iteritems():
            value = getattr(self, field)
            if value is None:
                continue
            if self._fields[field]._type == 'many2one':
                value = value.id
            if value != pattern_value:
                return False
        return True
