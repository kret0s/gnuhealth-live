# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from pywebdav.lib.constants import DAV_VERSION_1, DAV_VERSION_2

DAV_VERSION_1['version'] += ',calendar-auto-schedule'
DAV_VERSION_2['version'] += ',calendar-auto-schedule'
