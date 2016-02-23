# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from pywebdav.lib import propfind
from pywebdav.lib.errors import DAV_NotFound, DAV_Error
from trytond.protocols.webdav import TrytonDAVInterface, CACHE
from trytond.pool import Pool
from trytond.transaction import Transaction

TrytonDAVInterface.PROPS['urn:ietf:params:xml:ns:carddav'] = (
    'address-data',
    'addressbook-data',
    )
TrytonDAVInterface.M_NS['urn:ietf:params:xml:ns:carddav'] = '_get_carddav'

_mk_prop_response = propfind.PROPFIND.mk_prop_response


def mk_prop_response(self, uri, good_props, bad_props, doc):
    res = _mk_prop_response(self, uri, good_props, bad_props, doc)
    dbname, uri = TrytonDAVInterface.get_dburi(uri)
    if uri in ('Contacts', 'Contacts/'):
        ad = doc.createElement('addressbook')
        ad.setAttribute('xmlns', 'urn:ietf:params:xml:ns:carddav')
        vc = doc.createElement('vcard-collection')
        vc.setAttribute('xmlns', 'http://groupdav.org/')
        cols = res.getElementsByTagName('D:collection')
        if cols:
            cols[0].parentNode.appendChild(ad)
            cols[0].parentNode.appendChild(vc)
    return res

propfind.PROPFIND.mk_prop_response = mk_prop_response


def _get_carddav_address_data(self, uri):
    dbname, dburi = self._get_dburi(uri)
    if not dbname:
        raise DAV_NotFound
    pool = Pool(Transaction().cursor.database_name)
    try:
        Collection = pool.get('webdav.collection')
    except KeyError:
        raise DAV_NotFound
    try:
        return Collection.get_address_data(dburi, cache=CACHE)
    except DAV_Error:
        raise
    except Exception:
        raise DAV_Error(500)

TrytonDAVInterface._get_carddav_address_data = _get_carddav_address_data
TrytonDAVInterface._get_carddav_addressbook_data = _get_carddav_address_data
