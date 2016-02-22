# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.backend.table import TableHandlerInterface
import logging

logger = logging.getLogger(__name__)


class TableHandler(TableHandlerInterface):

    def __init__(self, cursor, model, module_name=None, history=False):
        super(TableHandler, self).__init__(cursor, model,
                module_name=module_name, history=history)
        self._columns = {}
        self._constraints = []
        self._fkeys = []
        self._indexes = []
        self._field2module = {}
        self._model = model

        # Create new table if necessary
        if not self.table_exist(self.cursor, self.table_name):
            if not self.history:
                self.cursor.execute('CREATE TABLE `%s` ('
                    'id BIGINT AUTO_INCREMENT NOT NULL, '
                    'PRIMARY KEY(id)'
                    ') ENGINE=InnoDB;' % self.table_name)
            else:
                self.cursor.execute('CREATE TABLE `%s` ('
                    '__id BIGINT AUTO_INCREMENT NOT NULL, '
                    'id BIGINT, '
                    'PRIMARY KEY(__id)'
                    ') ENGINE=InnoDB;' % self.table_name)

        self._update_definitions()
        if 'id' not in self._columns:
            if not self.history:
                self.cursor.execute('ALTER TABLE `%s` '
                    'ADD COLUMN id BIGINT AUTO_INCREMENT '
                    'NOT NULL PRIMARY KEY' % self.table_name)
            else:
                self.cursor.execute('ALTER TABLE `%s` '
                    'ADD COLUMN id BIGINT' % self.table_name)
            self._update_definitions()
        if self.history and '__id' not in self._columns:
            self.cursor.execute('ALTER TABLE `%s` '
                'ADD COLUMN __id BIGINT AUTO_INCREMENT '
                'NOT NULL PRIMARY KEY' % self.table_name)
        self._update_definitions()

    @staticmethod
    def table_exist(cursor, table_name):
        cursor.execute("SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            (cursor.database_name, table_name))
        return bool(cursor.rowcount)

    @staticmethod
    def table_rename(cursor, old_name, new_name):
        # Rename table
        if (TableHandler.table_exist(cursor, old_name)
                and not TableHandler.table_exist(cursor, new_name)):
            cursor.execute('ALTER TABLE `%s` RENAME TO `%s`'
                % (old_name, new_name))
        # Rename history table
        old_history = old_name + '__history'
        new_history = new_name + '__history'
        if (TableHandler.table_exist(cursor, old_history)
                and not TableHandler.table_exist(cursor, new_history)):
            cursor.execute('ALTER TABLE `%s` RENAME TO `%s`'
                % (old_history, new_history))

    @staticmethod
    def sequence_exist(cursor, sequence_name):
        return True

    @staticmethod
    def sequence_rename(cursor, old_name, new_name):
        pass

    def column_exist(self, column_name):
        return column_name in self._columns

    def column_rename(self, old_name, new_name, exception=False):
        if (self.column_exist(old_name)
                and not self.column_exist(new_name)):
            self.cursor.execute('ALTER TABLE `%s` '
                'RENAME COLUMN `%s` TO `%s`'
                % (self.table_name, old_name, new_name))
        elif exception and self.column_exist(new_name):
            raise Exception('Unable to rename column %s.%s to %s.%s: '
                '%s.%s already exist!'
                % (self.table_name, old_name, self.table_name, new_name,
                    self.table_name, new_name))

    def _update_definitions(self):
        # Fetch columns definitions from the table
        self.cursor.execute("SELECT column_name, character_maximum_length, "
                "data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            (self.cursor.database_name, self.table_name))
        self._columns = {}
        for line in self.cursor.fetchall():
            column, size, typname, nullable, default = line
            self._columns[column] = {
                'size': size,
                'typname': typname,
                'nullable': nullable == 'YES' and True or False,
                'default': default,
            }

        # fetch constraints for the table
        self.cursor.execute("SELECT constraint_name, constraint_type "
            "FROM information_schema.table_constraints "
            "WHERE table_schema = %s AND table_name = %s",
            (self.cursor.database_name, self.table_name))
        self._constraints = []
        self._fkeys = []
        for line in self.cursor.fetchall():
            conname, contype = line
            if contype not in ('PRIMARY KEY', 'FOREIGN KEY'):
                self._constraints.append(conname)
            elif contype == 'FOREIGN KEY':
                self._fkeys.append(conname)

        # Fetch indexes defined for the table
        self.cursor.execute('SHOW INDEXES FROM `%s`' % self.table_name)
        self._indexes = list(set(x[2] for x in self.cursor.fetchall()
            if x[2] != 'PRIMARY'))

        # Keep track of which module created each field
        self._field2module = {}
        if self.object_name is not None:
            self.cursor.execute('SELECT f.name, f.module '
                'FROM ir_model_field f '
                'JOIN ir_model m on (f.model=m.id) '
                'WHERE m.model = %s',
                (self.object_name,))
            for line in self.cursor.fetchall():
                self._field2module[line[0]] = line[1]

    def alter_size(self, column_name, column_type):
        self.cursor.execute('ALTER TABLE `%s` '
            'MODIFY COLUMN `%s` %s'
            % (self.table_name, column_name,
                self._column_definition(column_name)))
        self._update_definitions()

    def alter_type(self, column_name, column_type):
        self.cursor.execute('ALTER TABLE `%s` '
            'MODIFY COLUMN `%s` %s'
            % (self.table_name, column_name,
                self._column_definition(column_name, typname=column_type)))
        self._update_definitions()

    def db_default(self, column_name, value):
        self.cursor.execute('ALTER TABLE `%s` '
            'MODIFY COLUMN `%s` %s'
            % (self.table_name, column_name,
                self._column_definition(column_name, default=value)))
        self._update_definitions()

    def add_raw_column(self, column_name, column_type, column_format,
            default_fun=None, field_size=None, migrate=True, string=''):
        if self.column_exist(column_name):
            if not migrate:
                return
            base_type = column_type[0].lower()
            convert = {
                'char': 'varchar',
                'signed integer': 'bigint',
                }
            base_type = convert.get(base_type, base_type)
            if base_type != self._columns[column_name]['typname']:
                if (self._columns[column_name]['typname'], base_type) in (
                        ('varchar', 'text'),
                        ('text', 'varchar'),
                        ('date', 'timestamp'),
                        ('bigint', 'double'),
                        ('int', 'bigint'),
                        ('tinyint', 'bool'),
                        ('decimal', 'numeric'),
                        ):
                    self.alter_type(column_name, base_type)
                else:
                    logger.warning(
                        'Unable to migrate column %s on table %s '
                        'from %s to %s.',
                        column_name, self.table_name,
                        self._columns[column_name]['typname'], base_type)
            if (base_type == 'varchar'
                    and self._columns[column_name]['typname'] == 'varchar'):
                # Migrate size
                if field_size is None:
                    if self._columns[column_name]['size'] != 255:
                        self.alter_size(column_name, base_type)
                elif self._columns[column_name]['size'] == field_size:
                    pass
                else:
                    logger.warning(
                        'Unable to migrate column %s on table %s '
                        'from varchar(%s) to varchar(%s).',
                        column_name, self.table_name,
                        self._columns[column_name]['size'] > 0
                        and self._columns[column_name]['size'] or 255,
                        field_size)
            return

        column_type = column_type[1]
        self.cursor.execute('ALTER TABLE `%s` ADD COLUMN `%s` %s' %
                (self.table_name, column_name, column_type))

        if column_format:
            # check if table is non-empty:
            self.cursor.execute('SELECT 1 FROM `%s` limit 1' % self.table_name)
            if self.cursor.rowcount:
                # Populate column with default values:
                default = None
                if default_fun is not None:
                    default = default_fun()
                self.cursor.execute('UPDATE `' + self.table_name + '` '
                    'SET `' + column_name + '` = %s',
                    (column_format(default),))

        self._update_definitions()

    def add_fk(self, column_name, reference, on_delete=None):
        if on_delete is None:
            on_delete = 'SET NULL'
        conname = '%s_%s_fkey' % (self.table_name, column_name)
        if conname in self._fkeys:
            self.drop_fk(column_name)
        self.cursor.execute('ALTER TABLE `%s` '
            'ADD CONSTRAINT `%s` FOREIGN KEY (`%s`) '
            'REFERENCES `%s` (id) ON DELETE %s'
            % (self.table_name, conname, column_name, reference, on_delete))
        self._update_definitions()

    def drop_fk(self, column_name, table=None):
        conname = '%s_%s_fkey' % (self.table_name, column_name)
        if conname not in self._fkeys:
            return
        self.cursor.execute('ALTER TABLE `%s` '
            'DROP FOREIGN KEY `%s`' % (self.table_name, conname))
        self._update_definitions()

    def index_action(self, column_name, action='add', table=None):
        if isinstance(column_name, basestring):
            column_name = [column_name]
        index_name = ((table or self.table_name) + "_" + '_'.join(column_name)
            + "_index")
        # Index name length is limited to 64
        index_name = index_name[:64]

        for k in column_name:
            if k in self._columns:
                if self._columns[k]['typname'] in ('text', 'blob'):
                    return

        if action == 'add':
            if index_name in self._indexes:
                return
            self.cursor.execute('CREATE INDEX `' + index_name + '` '
                'ON `' + self.table_name + '` '
                '( ' + ','.join(['`' + x + '`' for x in column_name]) + ')')
            self._update_definitions()
        elif action == 'remove':
            if len(column_name) == 1:
                if (self._field2module.get(column_name[0], self.module_name)
                        != self.module_name):
                    return

            if index_name in self._indexes:
                self.cursor.execute('DROP INDEX `%s` ON `%s`'
                    % (index_name, self.table_name))
                self._update_definitions()
        else:
            raise Exception('Index action not supported!')

    def not_null_action(self, column_name, action='add'):
        if not self.column_exist(column_name):
            return

        if action == 'add':
            if not self._columns[column_name]['nullable']:
                return
            self.cursor.execute('SELECT id FROM `%s` '
                'WHERE `%s` IS NULL'
                % (self.table_name, column_name))
            if not self.cursor.rowcount:
                self.cursor.execute('ALTER TABLE `%s` '
                    'MODIFY COLUMN `%s` %s'
                    % (self.table_name, column_name,
                        self._column_definition(column_name, nullable=False)))
                self._update_definitions()
            else:
                logger.warning(
                    'Unable to set column %s '
                    'of table %s not null !\n'
                    'Try to re-run: '
                    'trytond.py --update=module\n'
                    'If it doesn\'t work, update records '
                    'and execute manually:\n'
                    'ALTER TABLE `%s` MODIFY COLUMN `%s` %s',
                    column_name, self.table_name, self.table_name,
                    column_name, self._column_definition(column_name,
                        nullable=False))
        elif action == 'remove':
            if self._columns[column_name]['nullable']:
                return
            if (self._field2module.get(column_name, self.module_name)
                    != self.module_name):
                return
            self.cursor.execute('ALTER TABLE `%s` '
                'MODIFY COLUMN `%s` %s'
                % (self.table_name, column_name,
                    self._column_definition(column_name, nullable=True)))
            self._update_definitions()
        else:
            raise Exception('Not null action not supported!')

    def add_constraint(self, ident, constraint, exception=False):
        ident = self.table_name + "_" + ident
        if ident in self._constraints:
            # This constrain already exists
            return
        try:
            self.cursor.execute('ALTER TABLE `%s` '
                'ADD CONSTRAINT `%s` %s'
                % (self.table_name, ident, constraint), constraint.params)
        except Exception:
            if exception:
                raise
            logger.warning(
                'unable to add \'%s\' constraint on table %s !\n'
                'If you want to have it, you should update the records '
                'and execute manually:\n'
                'ALTER table `%s` ADD CONSTRAINT `%s` %s',
                constraint, self.table_name, self.table_name, ident,
                constraint, exc_info=True)
        self._update_definitions()

    def drop_constraint(self, ident, exception=False, table=None):
        ident = (table or self.table_name) + "_" + ident
        if ident not in self._constraints:
            return
        try:
            self.cursor.execute('ALTER TABLE `%s` '
                'DROP CONSTRAINT `%s`'
                % (self.table_name, ident))
        except Exception:
            if exception:
                raise
            logger.warning(
                'unable to drop \'%s\' constraint on table %s!',
                ident, self.table_name)
        self._update_definitions()

    def drop_column(self, column_name, exception=False):
        if not self.column_exist(column_name):
            return
        try:
            self.cursor.execute(
                'ALTER TABLE `%s` DROP COLUMN `%s`' %
                (self.table_name, column_name))

        except Exception:
            if exception:
                raise
            logger.warning(
                'unable to drop \'%s\' column on table %s!',
                column_name, self.table_name)
        self._update_definitions()

    @staticmethod
    def drop_table(cursor, model, table, cascade=False):
        cursor.execute('DELETE from ir_model_data where '
            'model = %s', model)

        query = 'DROP TABLE `%s`' % table
        if cascade:
            query = query + ' CASCADE'
        cursor.execute(query)

    def _column_definition(self, column_name, typname=None, nullable=None,
            size=None, default=None):
        if typname is None:
            typname = self._columns[column_name]['typname']
        if nullable is None:
            nullable = self._columns[column_name]['nullable']
        if size is None:
            size = self._columns[column_name]['size']
        if default is None:
            default = self._columns[column_name]['default']
        res = ''
        if typname == 'varchar':
            if int(size) > 255:
                size = 255
            res = 'varchar(%s)' % str(size)
        elif typname == 'decimal':
            res = 'decimal(65, 30)'
        elif typname == 'double':
            res = 'double(255, 15)'
        else:
            res = typname
        # Default value for timestamp doesn't work
        if typname == 'timestamp' and not nullable:
            nullable = True
        if nullable:
            res += ' NULL'
        else:
            res += ' NOT NULL'
        if default is not None:
            res += ' DEFAULT %s' % default
        return res
