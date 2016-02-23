# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from pywebdav.lib import propfind
from pywebdav.lib.utils import get_uriparentpath
from trytond.protocols.webdav import TrytonDAVInterface

_mk_prop_response = propfind.PROPFIND.mk_prop_response


def mk_prop_response(self, uri, good_props, bad_props, doc):
    res = _mk_prop_response(self, uri, good_props, bad_props, doc)
    parent_uri = get_uriparentpath(uri and uri.strip('/') or '')
    if not parent_uri:
        return res
    dbname, parent_uri = TrytonDAVInterface.get_dburi(parent_uri)
    # Disable groupdav attribute for iPhone
    # if  parent_uri in ('Calendars', 'Calendars/'):
    #     vc = doc.createElement('vtodo-collection')
    #     vc.setAttribute('xmlns', 'http://groupdav.org/')
    #     cols = res.getElementsByTagName('D:collection')
    #     if cols:
    #         cols[0].parentNode.appendChild(vc)
    return res

propfind.PROPFIND.mk_prop_response = mk_prop_response
