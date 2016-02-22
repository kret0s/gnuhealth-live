# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import gettext

import gobject
import gtk
from .widget import Widget, TranslateMixin
from tryton.common import Tooltips
from tryton.common.entry_position import manage_entry_position
from tryton.common.selection import PopdownMixin, selection_shortcuts
from tryton.config import CONFIG

_ = gettext.gettext


class Char(Widget, TranslateMixin, PopdownMixin):
    "Char"

    def __init__(self, view, attrs):
        super(Char, self).__init__(view, attrs)

        self.widget = gtk.HBox()
        self.autocomplete = bool(attrs.get('autocomplete'))
        if self.autocomplete:
            self.entry = gtk.ComboBoxEntry()
            selection_shortcuts(self.entry)
            focus_entry = self.entry.get_child()
            self.set_popdown([], self.entry)
            self.entry.connect('changed', self.changed)
        else:
            self.entry = gtk.Entry()
            focus_entry = self.entry
        self.mnemonic_widget = focus_entry

        focus_entry.set_property('activates_default', True)
        focus_entry.connect('activate', self.sig_activate)
        focus_entry.connect('focus-out-event', lambda x, y: self._focus_out())
        focus_entry.connect('key-press-event', self.send_modified)
        manage_entry_position(focus_entry)
        expand, fill = True, True
        if attrs.get('size'):
            expand, fill = False, False
        self.widget.pack_start(self.entry, expand=expand, fill=fill)

        if attrs.get('translate'):
            self.entry.set_icon_from_stock(gtk.ENTRY_ICON_SECONDARY,
                'tryton-locale')
            self.entry.connect('icon-press', self.translate)

    def translate_widget(self):
        entry = gtk.Entry()
        entry.set_property('activates_default', True)
        if self.record:
            field_size = self.record.expr_eval(self.attrs.get('size'))
            entry.set_width_chars(field_size or -1)
            entry.set_max_length(field_size or 0)
        return entry

    @staticmethod
    def translate_widget_set(widget, value):
        widget.set_text(value or '')

    @staticmethod
    def translate_widget_get(widget):
        return widget.get_text()

    @staticmethod
    def translate_widget_set_readonly(widget, value):
        widget.set_editable(not value)
        widget.props.sensitive = not value

    def changed(self, combobox):
        def focus_out():
            if combobox.props.window:
                self._focus_out()
        # Only when changed from pop list
        if not combobox.get_child().has_focus():
            # Must be deferred because it triggers a display of the form
            gobject.idle_add(focus_out)

    @property
    def modified(self):
        if self.record and self.field:
            entry = self.entry.get_child() if self.autocomplete else self.entry
            value = entry.get_text() or ''
            return self.field.get_client(self.record) != value
        return False

    def set_value(self, record, field):
        entry = self.entry.get_child() if self.autocomplete else self.entry
        value = entry.get_text() or ''
        return field.set_client(record, value)

    def get_value(self):
        entry = self.entry.get_child() if self.autocomplete else self.entry
        return entry.get_text()

    def display(self, record, field):
        super(Char, self).display(record, field)
        if self.autocomplete:
            if record:
                selection = record.autocompletion.get(self.field_name, [])
            else:
                selection = []
            self.set_popdown([(x, x) for x in selection], self.entry)

        # Set size
        if self.autocomplete:
            size_entry = self.entry.get_child()
        else:
            size_entry = self.entry
        if record:
            field_size = record.expr_eval(self.attrs.get('size'))
            size_entry.set_width_chars(field_size or -1)
            size_entry.set_max_length(field_size or 0)
        else:
            size_entry.set_width_chars(-1)
            size_entry.set_max_length(0)

        if not field:
            value = ''
        else:
            value = field.get_client(record)

        if not self.autocomplete:
            self.entry.set_text(value)
        else:
            self.entry.handler_block_by_func(self.changed)
            if not self.set_popdown_value(self.entry, value) or not value:
                self.entry.get_child().set_text(value)
            self.entry.handler_unblock_by_func(self.changed)

    def _readonly_set(self, value):
        sensitivity = {True: gtk.SENSITIVITY_OFF, False: gtk.SENSITIVITY_AUTO}
        super(Char, self)._readonly_set(value)
        if self.autocomplete:
            self.entry.get_child().set_editable(not value)
            self.entry.set_button_sensitivity(sensitivity[value])
        else:
            self.entry.set_editable(not value)
        if value and CONFIG['client.fast_tabbing']:
            self.widget.set_focus_chain([])
        else:
            self.widget.unset_focus_chain()


class Password(Char):

    def __init__(self, view, attrs):
        super(Password, self).__init__(view, attrs)
        self.entry.props.visibility = False

        self.visibility_checkbox = gtk.CheckButton()
        self.visibility_checkbox.connect('toggled', self.toggle_visibility)
        Tooltips().set_tip(self.visibility_checkbox, _('Show plain text'))
        self.widget.pack_start(self.visibility_checkbox, expand=False)

    def _readonly_set(self, value):
        super(Char, self)._readonly_set(value)
        self.entry.set_editable(not value)
        self.visibility_checkbox.props.visible = not value
        if value and CONFIG['client.fast_tabbing']:
            self.widget.set_focus_chain([])
        else:
            self.widget.unset_focus_chain()

    def toggle_visibility(self, button):
        self.entry.props.visibility = not self.entry.props.visibility
