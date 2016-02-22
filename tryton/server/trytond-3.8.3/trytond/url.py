# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

import encodings.idna
import urllib
import socket

from trytond.config import config
from trytond.transaction import Transaction

__all__ = ['URLMixin']

HOSTNAME = (config.get('jsonrpc', 'hostname')
    or unicode(socket.getfqdn(), 'utf8'))
HOSTNAME = '.'.join(encodings.idna.ToASCII(part) if part else ''
    for part in HOSTNAME.split('.'))


class URLAccessor(object):

    def __get__(self, inst, cls):
        from trytond.model import Model
        from trytond.wizard import Wizard
        from trytond.report import Report

        url_part = {}
        if issubclass(cls, Model):
            url_part['type'] = 'model'
        elif issubclass(cls, Wizard):
            url_part['type'] = 'wizard'
        elif issubclass(cls, Report):
            url_part['type'] = 'report'
        else:
            raise NotImplementedError

        url_part['name'] = cls.__name__
        url_part['database'] = Transaction().cursor.database_name

        local_part = urllib.quote('%(database)s/%(type)s/%(name)s' % url_part)
        if isinstance(inst, Model) and inst.id:
            local_part += '/%d' % inst.id
        return 'tryton://%s/%s' % (HOSTNAME, local_part)


class URLMixin(object):

        __url__ = URLAccessor()
