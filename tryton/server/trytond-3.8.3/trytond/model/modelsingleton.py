# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.model import ModelStorage


class ModelSingleton(ModelStorage):
    """
    Define a singleton model in Tryton.
    """

    @classmethod
    def get_singleton(cls):
        '''
        Return the instance of the unique record if there is one.
        '''
        singletons = super(ModelSingleton, cls).search([], limit=1)
        if singletons:
            return singletons[0]

    @classmethod
    def create(cls, vlist):
        assert len(vlist) == 1
        singleton = cls.get_singleton()
        if not singleton:
            return super(ModelSingleton, cls).create(vlist)
        cls.write([singleton], vlist[0])
        return [singleton]

    @classmethod
    def read(cls, ids, fields_names=None):
        singleton = cls.get_singleton()
        if not singleton:
            if not fields_names:
                fields_names = cls._fields.keys()
            fname_no_rec_name = [f for f in fields_names if '.' not in f]
            res = cls.default_get(fname_no_rec_name,
                with_rec_name=len(fname_no_rec_name) != len(fields_names))
            for field_name in fields_names:
                if field_name not in res:
                    res[field_name] = None
            for field_name in res.keys():
                if field_name not in fields_names:
                    del res[field_name]
            res['id'] = ids[0]
            return [res]
        res = super(ModelSingleton, cls).read([singleton.id],
            fields_names=fields_names)
        res[0]['id'] = ids[0]
        return res

    @classmethod
    def write(cls, records, values, *args):
        singleton = cls.get_singleton()
        if not singleton:
            singleton, = cls.create([values])
        actions = (records, values) + args
        args = []
        for values in actions[1:None:2]:
            args.extend(([singleton], values))
        return super(ModelSingleton, cls).write(*args)

    @classmethod
    def delete(cls, records):
        singleton = cls.get_singleton()
        if not singleton:
            return
        return super(ModelSingleton, cls).delete([singleton])

    @classmethod
    def copy(cls, records, default=None):
        if default:
            cls.write(records, default)
        return records

    @classmethod
    def search(cls, domain, offset=0, limit=None, order=None, count=False):
        res = super(ModelSingleton, cls).search(domain, offset=offset,
                limit=limit, order=order, count=count)
        if not res and not domain:
            if count:
                return 1
            return [cls(1)]
        return res

    @classmethod
    def default_get(cls, fields_names, with_rec_name=True):
        if '_timestamp' in fields_names:
            fields_names = list(fields_names)
            fields_names.remove('_timestamp')
        default = super(ModelSingleton, cls).default_get(fields_names,
                with_rec_name=with_rec_name)
        singleton = cls.get_singleton()
        if singleton:
            if with_rec_name:
                fields_names = fields_names[:]
                for field in fields_names[:]:
                    if cls._fields[field]._type in ('many2one',):
                        fields_names.append(field + '.rec_name')
            default, = cls.read([singleton.id], fields_names=fields_names)
            for field in (x for x in default.keys() if x not in fields_names):
                del default[field]
        return default
