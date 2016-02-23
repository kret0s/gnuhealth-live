# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from pywebdav.lib.errors import DAV_NotFound, DAV_Forbidden
from pywebdav.lib.constants import COLLECTION, OBJECT
from sql.functions import Extract
from sql.aggregate import Max
from sql.conditionals import Coalesce

from trytond.tools import reduce_ids, grouped_slice
from trytond.transaction import Transaction
from trytond.cache import Cache
from trytond.pool import Pool, PoolMeta

__all__ = ['Collection']
__metaclass__ = PoolMeta


CARDDAV_NS = 'urn:ietf:params:xml:ns:carddav'


class Collection:
    __name__ = "webdav.collection"
    _vcard_cache = Cache('webdav.collection.vcard', context=False)

    @classmethod
    def vcard(cls, uri):
        '''
        Return party ids of the vcard in uri or False
        '''
        Party = Pool().get('party.party')
        party_id = cls._vcard_cache.get(uri, -1)
        if party_id != -1:
            return party_id

        if uri and uri.startswith('Contacts/'):
            uuid = uri[9:-4]
            parties = Party.search([
                    ('uuid', '=', uuid),
                    ], limit=1)
            if parties:
                party_id = parties[0].id
            else:
                party_id = None
        elif uri == 'Contacts':
            party_id = None
        else:
            party_id = False
        cls._vcard_cache.set(uri, party_id)
        return party_id

    @classmethod
    def _carddav_filter_domain(cls, filter):
        '''
        Return a domain for the carddav filter
        '''
        pool = Pool()
        Address = pool.get('party.address')
        ContactMechanism = pool.get('party.contact_mechanism')

        res = []
        if not filter:
            return []
        if filter.localName == 'addressbook-query':
            addressbook_filter = filter.getElementsByTagNameNS(
                    'urn:ietf:params:xml:ns:carddav', 'filter')[0]
            if addressbook_filter.hasAttribute('test') \
                    and addressbook_filter.getAttribute('test') == 'allof':
                res.append('AND')
            else:
                res.append('OR')

            for prop in addressbook_filter.childNodes:
                name = prop.getAttribute('name').lower()
                field = None
                if name == 'fn':
                    field = 'rec_name'
                if name == 'n':
                    field = 'name'
                if name == 'uid':
                    field = 'uid'
                if name == 'adr':
                    field = 'rec_name'
                if name in ('mail', 'tel'):
                    field = 'value'
                if field:
                    res2 = []
                    if (prop.hasAttribute('test')
                            and (prop.addressbook_filter.getAttribute('test')
                                == 'allof')):
                        res2.append('AND')
                    else:
                        res2.append('OR')
                    if prop.getElementsByTagNameNS(CARDDAV_NS,
                            'is-not-defined'):
                        res2.append((field, '=', None))
                    for text_match in prop.getElementsByTagNameNS(CARDDAV_NS,
                            'text-match'):
                        value = text_match.firstChild.data
                        negate = False
                        if text_match.hasAttribute('negate-condition') \
                                and text_match.getAttribute(
                                        'negate-condition') == 'yes':
                            negate = True
                        type = 'contains'
                        if text_match.hasAttribute('match-type'):
                            type = text_match.getAttribute('match-type')
                        if type == 'equals':
                            pass
                        elif type in ('contains', 'substring'):
                            value = '%' + value + '%'
                        elif type == 'starts-with':
                            value = value + '%'
                        elif type == 'ends-with':
                            value = '%' + value
                        if not negate:
                            res2.append((field, 'ilike', value))
                        else:
                            res2.append((field, 'not ilike', value))
                    if name == 'adr':
                        domain = res2
                        addresses = Address.search(domain)
                        res = [('addresses', 'in', [a.id for a in addresses])]
                    elif name in ('mail', 'tel'):
                        if name == 'mail':
                            type = ['email']
                        else:
                            type = ['phone', 'mobile']
                        domain = [('type', 'in', type), res2]
                        contact_mechanisms = ContactMechanism.search(
                            domain)
                        res2 = [
                            ('contact_mechanisms', 'in',
                                [c.id for c in contact_mechanisms])
                            ]
                    res.append(res2)
        return res

    @classmethod
    def get_childs(cls, uri, filter=None, cache=None):
        Party = Pool().get('party.party')

        if uri in ('Contacts', 'Contacts/'):
            domain = cls._carddav_filter_domain(filter)
            parties = Party.search(domain)
            if cache is not None:
                cache.setdefault('_contact', {})
                for party in parties:
                    cache['_contact'][party.id] = {}
            return [x.uuid + '.vcf' for x in parties]
        party_id = cls.vcard(uri)
        if party_id or party_id is None:
            return []
        res = super(Collection, cls).get_childs(uri, filter=filter,
                cache=cache)
        if not uri and not filter:
            res.append('Contacts')
        return res

    @classmethod
    def get_resourcetype(cls, uri, cache=None):
        party_id = cls.vcard(uri)
        if party_id:
            return OBJECT
        elif party_id is None:
            return COLLECTION
        return super(Collection, cls).get_resourcetype(uri, cache=cache)

    @classmethod
    def get_contenttype(cls, uri, cache=None):
        if cls.vcard(uri):
            return 'text/x-vcard'
        return super(Collection, cls).get_contenttype(uri, cache=cache)

    @classmethod
    def get_creationdate(cls, uri, cache=None):
        Party = Pool().get('party.party')
        party = Party.__table__()
        party_id = cls.vcard(uri)

        cursor = Transaction().cursor

        if party_id is None:
            raise DAV_NotFound
        if party_id:
            if cache is not None:
                cache.setdefault('_contact', {})
                ids = cache['_contact'].keys()
                if party_id not in ids:
                    ids.append(party_id)
                elif 'creationdate' in cache['_contact'][party_id]:
                    return cache['_contact'][party_id]['creationdate']
            else:
                ids = [party_id]
            res = None
            for sub_ids in grouped_slice(ids):
                red_sql = reduce_ids(party.id, sub_ids)
                cursor.execute(*party.select(party.id,
                        Extract('EPOCH', party.create_date),
                        where=red_sql))
                for party_id2, date in cursor.fetchall():
                    if party_id2 == party_id:
                        res = date
                    if cache is not None:
                        cache['_contact'].setdefault(party_id2, {})
                        cache['_contact'][party_id2]['creationdate'] = date
            if res is not None:
                return res
        return super(Collection, cls).get_creationdate(uri, cache=cache)

    @classmethod
    def get_lastmodified(cls, uri, cache=None):
        pool = Pool()
        Party = pool.get('party.party')
        Address = pool.get('party.address')
        ContactMechanism = pool.get('party.contact_mechanism')
        party = Party.__table__()
        address = Address.__table__()
        contact_mechanism = ContactMechanism.__table__()

        cursor = Transaction().cursor

        party_id = cls.vcard(uri)
        if party_id:
            if cache is not None:
                cache.setdefault('_contact', {})
                ids = cache['_contact'].keys()
                if party_id not in ids:
                    ids.append(party_id)
                elif 'lastmodified' in cache['_contact'][party_id]:
                    return cache['_contact'][party_id]['lastmodified']
            else:
                ids = [party_id]
            res = None
            for sub_ids in grouped_slice(ids):
                red_sql = reduce_ids(party.id, sub_ids)
                cursor.execute(*party.join(address, 'LEFT',
                        condition=party.id == address.party
                        ).join(contact_mechanism, 'LEFT',
                        condition=party.id == contact_mechanism.party
                        ).select(party.id,
                        Max(Extract('EPOCH', Coalesce(party.write_date,
                                    party.create_date))),
                        Max(Extract('EPOCH', Coalesce(address.write_date,
                                    address.create_date))),
                        Max(Extract('EPOCH', Coalesce(
                                    contact_mechanism.write_date,
                                    contact_mechanism.create_date))),
                        where=red_sql,
                        group_by=party.id))
                for party_id2, date_p, date_a, date_c in cursor.fetchall():
                    date = max(date_p, date_a, date_c)
                    if party_id2 == party_id:
                        res = date
                    if cache is not None:
                        cache['_contact'].setdefault(party_id2, {})
                        cache['_contact'][party_id2]['lastmodified'] = date
            if res is not None:
                return res
        return super(Collection, cls).get_lastmodified(uri, cache=cache)

    @classmethod
    def get_data(cls, uri, cache=None):
        Vcard = Pool().get('party_vcarddav.party.vcard', type='report')
        party_id = cls.vcard(uri)
        if party_id is None:
            raise DAV_NotFound
        if party_id:
            val = Vcard.execute([party_id],
                {'id': party_id, 'ids': [party_id]})
            return str(val[1])
        return super(Collection, cls).get_data(uri, cache=cache)

    @classmethod
    def get_address_data(cls, uri, cache=None):
        Vcard = Pool().get('party_vcarddav.party.vcard', type='report')
        party_id = cls.vcard(uri)
        if not party_id:
            raise DAV_NotFound
        return Vcard.execute([party_id],
            {'id': party_id, 'ids': [party_id]},
            ).decode('utf-8')

    @classmethod
    def put(cls, uri, data, content_type, cache=None):
        import vobject
        Party = Pool().get('party.party')

        party_id = cls.vcard(uri)
        if party_id is None:
            vcard = vobject.readOne(data)
            values = Party().vcard2values(vcard)
            try:
                party_id, = Party.create([values])
            except Exception:
                raise DAV_Forbidden
            party = Party(party_id)
            return (Transaction().cursor.database_name + '/Contacts/' +
                    party.uuid + '.vcf')
        if party_id:
            party = Party(party_id)
            vcard = vobject.readOne(data)
            values = party.vcard2values(vcard)
            try:
                Party.write([party], values)
            except Exception:
                raise DAV_Forbidden
            return
        return super(Collection, cls).put(uri, data, content_type,
            cache=cache)

    @classmethod
    def mkcol(cls, uri, cache=None):
        party_id = cls.vcard(uri)
        if party_id is None:
            raise DAV_Forbidden
        if party_id:
            raise DAV_Forbidden
        return super(Collection, cls).mkcol(uri, cache=cache)

    @classmethod
    def rmcol(cls, uri, cache=None):
        party_id = cls.vcard(uri)
        if party_id is None:
            raise DAV_Forbidden
        if party_id:
            raise DAV_Forbidden
        return super(Collection, cls).rmcol(uri, cache=cache)

    @classmethod
    def rm(cls, uri, cache=None):
        Party = Pool().get('party.party')

        party_id = cls.vcard(uri)
        if party_id is None:
            raise DAV_Forbidden
        if party_id:
            try:
                Party.delete([Party(party_id)])
            except Exception:
                raise DAV_Forbidden
            return 200
        return super(Collection, cls).rm(uri, cache=cache)

    @classmethod
    def exists(cls, uri, cache=None):
        party_id = cls.vcard(uri)
        if party_id is None or party_id:
            if party_id:
                return 1
            if uri in ('Contacts', 'Contacts/'):
                return 1
            return 0
        return super(Collection, cls).exists(uri, cache=cache)
