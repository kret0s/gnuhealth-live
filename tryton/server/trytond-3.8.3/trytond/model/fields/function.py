# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

import inspect
import copy
from trytond.model.fields.field import Field
from trytond.tools import is_instance_method
from trytond.transaction import Transaction


class Function(Field):
    '''
    Define function field (any).
    '''

    def __init__(self, field, getter, setter=None, searcher=None,
            loading='lazy'):
        '''
        :param field: The field of the function.
        :param getter: The name of the function for getting values.
        :param setter: The name of the function to set value.
        :param searcher: The name of the function to search.
        :param loading: Define how the field must be loaded:
            ``lazy`` or ``eager``.
        '''
        assert isinstance(field, Field)
        self._field = field
        self._type = field._type
        self.getter = getter
        self.setter = setter
        if not self.setter:
            self._field.readonly = True
        self.searcher = searcher
        assert loading in ('lazy', 'eager'), \
            'loading must be "lazy" or "eager"'
        self.loading = loading

    __init__.__doc__ += Field.__init__.__doc__

    def __copy__(self):
        return Function(copy.copy(self._field), self.getter,
            setter=self.setter, searcher=self.searcher, loading=self.loading)

    def __deepcopy__(self, memo):
        return Function(copy.deepcopy(self._field, memo), self.getter,
            setter=self.setter, searcher=self.searcher, loading=self.loading)

    def __getattr__(self, name):
        return getattr(self._field, name)

    def __getitem__(self, name):
        return self._field[name]

    def __setattr__(self, name, value):
        if name in ('_field', '_type', 'getter', 'setter', 'searcher', 'name'):
            object.__setattr__(self, name, value)
            if name != 'name':
                return
        setattr(self._field, name, value)

    @property
    def sql_type(self):
        raise AttributeError

    def convert_domain(self, domain, tables, Model):
        name, operator, value = domain[:3]
        if not self.searcher:
            Model.raise_user_error('search_function_missing', name)
        return getattr(Model, self.searcher)(name, domain)

    def get(self, ids, Model, name, values=None):
        '''
        Call the getter.
        If the function has ``names`` in the function definition then
        it will call it with a list of name.
        '''
        with Transaction().set_context(_check_access=False):
            method = getattr(Model, self.getter)
            instance_method = is_instance_method(Model, self.getter)

            def call(name):
                records = Model.browse(ids)
                if not instance_method:
                    return method(records, name)
                else:
                    return dict((r.id, method(r, name)) for r in records)
            if isinstance(name, list):
                names = name
                # Test is the function works with a list of names
                if 'names' in inspect.getargspec(method)[0]:
                    return call(names)
                return dict((name, call(name)) for name in names)
            else:
                # Test is the function works with a list of names
                if 'names' in inspect.getargspec(method)[0]:
                    name = [name]
                return call(name)

    def set(self, Model, name, ids, value, *args):
        '''
        Call the setter.
        '''
        with Transaction().set_context(_check_access=False):
            if self.setter:
                # TODO change setter API to use sequence of records, value
                setter = getattr(Model, self.setter)
                args = iter((ids, value) + args)
                for ids, value in zip(args, args):
                    setter(Model.browse(ids), name, value)

    def __set__(self, inst, value):
        self._field.__set__(inst, value)
