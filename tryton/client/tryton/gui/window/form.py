# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
"Form"
import gettext
import gtk
import gobject
from tryton.gui.window.view_form.screen import Screen
from tryton.action import Action
from tryton.gui import Main
from tryton.gui.window import Window
from tryton.gui.window.win_export import WinExport
from tryton.gui.window.win_import import WinImport
from tryton.gui.window.attachment import Attachment
from tryton.gui.window.revision import Revision
from tryton.signal_event import SignalEvent
from tryton.common import message, sur, sur_3b, timezoned_date
import tryton.common as common
from tryton.common import RPCExecute, RPCException
from tryton.common.datetime_strftime import datetime_strftime
from tryton import plugins

from tabcontent import TabContent

_ = gettext.gettext


class Form(SignalEvent, TabContent):
    "Form"

    toolbar_def = [
        ('new', 'tryton-new', _('New'), _('Create a new record'),
            'sig_new'),
        ('save', 'tryton-save', _('Save'), _('Save this record'),
            'sig_save'),
        ('switch', 'tryton-fullscreen', _('Switch'), _('Switch view'),
            'sig_switch'),
        ('reload', 'tryton-refresh', _('_Reload'), _('Reload'),
            'sig_reload'),
        (None,) * 5,
        ('previous', 'tryton-go-previous', _('Previous'),
            _('Previous Record'), 'sig_previous'),
        ('next', 'tryton-go-next', _('Next'), _('Next Record'),
            'sig_next'),
        (None,) * 5,
        ('attach', 'tryton-attachment', _('Attachment(0)'),
            _('Add an attachment to the record'), 'sig_attach'),
    ]
    menu_def = [
        (_('_New'), 'tryton-new', 'sig_new', '<tryton>/Form/New'),
        (_('_Save'), 'tryton-save', 'sig_save', '<tryton>/Form/Save'),
        (_('_Switch View'), 'tryton-fullscreen', 'sig_switch',
            '<tryton>/Form/Switch View'),
        (_('_Reload/Undo'), 'tryton-refresh', 'sig_reload',
            '<tryton>/Form/Reload'),
        (_('_Duplicate'), 'tryton-copy', 'sig_copy',
            '<tryton>/Form/Duplicate'),
        (_('_Delete...'), 'tryton-delete', 'sig_remove',
            '<tryton>/Form/Delete'),
        (None,) * 4,
        (_('_Previous'), 'tryton-go-previous', 'sig_previous',
            '<tryton>/Form/Previous'),
        (_('_Next'), 'tryton-go-next', 'sig_next', '<tryton>/Form/Next'),
        (_('_Search'), 'tryton-find', 'sig_search', '<tryton>/Form/Search'),
        (_('View _Logs...'), None, 'sig_logs', None),
        (_('Show revisions...'), 'tryton-clock', 'revision', None),
        (None,) * 4,
        (_('_Close Tab'), 'tryton-close', 'sig_win_close',
            '<tryton>/Form/Close'),
        (None,) * 4,
        (_('A_ttachments...'), 'tryton-attachment', 'sig_attach',
            '<tryton>/Form/Attachments'),
        (_('_Actions...'), 'tryton-executable', 'sig_action',
            '<tryton>/Form/Actions'),
        (_('_Relate...'), 'tryton-go-jump', 'sig_relate',
            '<tryton>/Form/Relate'),
        (None,) * 4,
        (_('_Report...'), 'tryton-print-open', 'sig_print_open',
            '<tryton>/Form/Report'),
        (_('_E-Mail...'), 'tryton-print-email', 'sig_print_email',
            '<tryton>/Form/Email'),
        (_('_Print...'), 'tryton-print', 'sig_print',
            '<tryton>/Form/Print'),
        (None,) * 4,
        (_('_Export Data...'), 'tryton-save-as', 'sig_save_as',
            '<tryton>/Form/Export Data'),
        (_('_Import Data...'), None, 'sig_import',
            '<tryton>/Form/Import Data'),
    ]

    def __init__(self, model, res_id=False, domain=None, order=None, mode=None,
            view_ids=None, context=None, name=False, limit=None,
            search_value=None, tab_domain=None):
        super(Form, self).__init__()

        if not mode:
            mode = ['tree', 'form']
        if domain is None:
            domain = []
        if view_ids is None:
            view_ids = []

        self.model = model
        self.res_id = res_id
        self.domain = domain
        self.mode = mode
        self.context = context
        self.view_ids = view_ids
        self.dialogs = []

        self.screen = Screen(self.model, mode=mode, context=context,
            view_ids=view_ids, domain=domain, limit=limit, order=order,
            search_value=search_value, tab_domain=tab_domain)
        self.screen.widget.show()

        if not name:
            self.name = self.screen.current_view.title
        else:
            self.name = name

        if self.model not in common.MODELHISTORY:
            self.menu_def = self.menu_def[:]
            # Remove callback to revision
            self.menu_def[11] = (self.menu_def[11][:2] + (None,)
                + self.menu_def[11][3:])

        self.create_tabcontent()

        self.url_entry = url_entry = gtk.Entry()
        url_entry.show()
        url_entry.set_editable(False)
        style = url_entry.get_style()
        url_entry.modify_bg(gtk.STATE_ACTIVE,
            style.bg[gtk.STATE_INSENSITIVE])
        self.widget.pack_start(url_entry, False, False)

        access = common.MODELACCESS[self.model]
        for button, access_type in (
                ('new', 'create'),
                ('save', 'write'),
                ):
            self.buttons[button].props.sensitive = access[access_type]

        self.screen.signal_connect(self, 'record-message',
            self._record_message)

        self.screen.signal_connect(self, 'record-modified',
            lambda *a: gobject.idle_add(self._record_modified, *a))
        self.screen.signal_connect(self, 'record-saved', self._record_saved)
        self.screen.signal_connect(self, 'attachment-count',
                self._attachment_count)

        if res_id not in (None, False):
            if isinstance(res_id, (int, long)):
                res_id = [res_id]
            self.screen.load(res_id)
        else:
            if self.screen.current_view.view_type == 'form':
                self.sig_new(None, autosave=False)
            if self.screen.current_view.view_type \
                    in ('tree', 'graph', 'calendar'):
                self.screen.search_filter()

        self.update_revision()

    def get_toolbars(self):
        try:
            return RPCExecute('model', self.model, 'view_toolbar_get',
                context=self.screen.context)
        except RPCException:
            return {}

    def widget_get(self):
        return self.screen.widget

    def __eq__(self, value):
        if not value:
            return False
        if not isinstance(value, Form):
            return False
        return (self.model == value.model
            and self.res_id == value.res_id
            and self.domain == value.domain
            and self.mode == value.mode
            and self.view_ids == value.view_ids
            and self.screen.context == value.screen.context
            and self.name == value.name
            and self.screen.limit == value.screen.limit
            and self.screen.search_value == value.screen.search_value)

    def destroy(self):
        self.screen.destroy()

    def sig_attach(self, widget=None):
        record = self.screen.current_record
        if not record or record.id < 0:
            return
        Attachment(record,
            lambda: self.update_attachment_count(reload=True))

    def update_attachment_count(self, reload=False):
        record = self.screen.current_record
        if record:
            attachment_count = record.get_attachment_count(reload=reload)
        else:
            attachment_count = 0
        self._attachment_count(None, attachment_count)

    def _attachment_count(self, widget, signal_data):
        label = _('Attachment(%d)') % signal_data
        self.buttons['attach'].set_label(label)
        if signal_data:
            self.buttons['attach'].set_stock_id('tryton-attachment-hi')
        else:
            self.buttons['attach'].set_stock_id('tryton-attachment')
        record = self.screen.current_record
        self.buttons['attach'].props.sensitive = bool(
            record.id >= 0 if record else False)

    def sig_switch(self, widget=None):
        if not self.modified_save():
            return
        self.screen.switch_view()

    def sig_logs(self, widget=None):
        current_record = self.screen.current_record
        if not current_record or current_record.id < 0:
            self.message_info(
                _('You have to select one record.'), gtk.MESSAGE_INFO)
            return False

        fields = [
            ('id', _('ID:')),
            ('create_uid.rec_name', _('Creation User:')),
            ('create_date', _('Creation Date:')),
            ('write_uid.rec_name', _('Latest Modification by:')),
            ('write_date', _('Latest Modification Date:')),
        ]

        try:
            res = RPCExecute('model', self.model, 'read', [current_record.id],
                [x[0] for x in fields], context=self.screen.context)
        except RPCException:
            return
        date_format = self.screen.context.get('date_format', '%x')
        datetime_format = date_format + ' %X.%f'
        message_str = ''
        for line in res:
            for (key, val) in fields:
                value = str(line.get(key, False) or '/')
                if line.get(key, False) \
                        and key in ('create_date', 'write_date'):
                    date = timezoned_date(line[key])
                    value = common.datetime_strftime(date, datetime_format)
                message_str += val + ' ' + value + '\n'
        message_str += _('Model:') + ' ' + self.model
        message(message_str)
        return True

    def revision(self, widget=None):
        if not self.modified_save():
            return
        current_id = (self.screen.current_record.id
            if self.screen.current_record else None)
        try:
            revisions = RPCExecute('model', self.model, 'history_revisions',
                [r.id for r in self.screen.selected_records])
        except RPCException:
            return
        revision = self.screen.context.get('_datetime')
        format_ = self.screen.context.get('date_format', '%x')
        format_ += ' %X.%f'
        revision = Revision(revisions, revision, format_).run()
        # Prevent too old revision in form view
        if (self.screen.current_view.view_type == 'form'
                and revision
                and revision < revisions[-1][0]):
                revision = revisions[-1][0]
        if revision != self.screen.context.get('_datetime'):
            self.screen.clear()
            # Update root group context that will be propagated
            self.screen.group._context['_datetime'] = revision
            if self.screen.current_view.view_type != 'form':
                self.screen.search_filter(
                    self.screen.screen_container.get_text())
            else:
                # Test if record exist in revisions
                self.screen.load([current_id])
            self.screen.display(set_cursor=True)
            self.update_revision()

    def update_revision(self):
        revision = self.screen.context.get('_datetime')
        if revision:
            format_ = self.screen.context.get('date_format', '%x')
            format_ += ' %X.%f'
            revision = datetime_strftime(revision, format_)
            self.title.set_label('%s @ %s' % (self.name, revision))
        else:
            self.title.set_label(self.name)
        for button in ('new', 'save'):
            self.buttons[button].props.sensitive = not revision

    def sig_remove(self, widget=None):
        if not common.MODELACCESS[self.model]['delete']:
            return
        if self.screen.current_view.view_type == 'form':
            msg = _('Are you sure to remove this record?')
        else:
            msg = _('Are you sure to remove those records?')
        if sur(msg):
            if not self.screen.remove(delete=True, force_remove=True):
                self.message_info(_('Records not removed.'), gtk.MESSAGE_ERROR)
            else:
                self.message_info(_('Records removed.'), gtk.MESSAGE_INFO)

    def sig_import(self, widget=None):
        WinImport(self.model, self.screen.context)

    def sig_save_as(self, widget=None):
        export = WinExport(self.model,
            [r.id for r in self.screen.selected_records],
            context=self.screen.context)
        for name in self.screen.current_view.get_fields():
            export.sel_field(name)

    def sig_new(self, widget=None, autosave=True):
        if not common.MODELACCESS[self.model]['create']:
            return
        if autosave:
            if not self.modified_save():
                return
        self.screen.new()
        self.message_info()
        self.activate_save()

    def sig_copy(self, widget=None):
        if not common.MODELACCESS[self.model]['create']:
            return
        if not self.modified_save():
            return
        if self.screen.copy():
            self.message_info(_('Working now on the duplicated record(s).'),
                gtk.MESSAGE_INFO)

    def sig_save(self, widget=None):
        if widget:
            # Called from button so we must save the tree state
            self.screen.save_tree_state()
        if not common.MODELACCESS[self.model]['write']:
            return
        if self.screen.save_current():
            self.message_info(_('Record saved.'), gtk.MESSAGE_INFO)
            return True
        else:
            self.message_info(self.screen.invalid_message(), gtk.MESSAGE_ERROR)
            return False

    def sig_previous(self, widget=None):
        if not self.modified_save():
            return
        self.screen.display_prev()
        self.message_info()
        self.activate_save()

    def sig_next(self, widget=None):
        if not self.modified_save():
            return
        self.screen.display_next()
        self.message_info()
        self.activate_save()

    def sig_reload(self, test_modified=True):
        if test_modified:
            if not self.modified_save():
                return False
        else:
            self.screen.save_tree_state(store=False)
        self.screen.cancel_current()
        set_cursor = False
        record_id = (self.screen.current_record.id
            if self.screen.current_record else None)
        if self.screen.current_view.view_type != 'form':
            self.screen.search_filter(self.screen.screen_container.get_text())
            for record in self.screen.group:
                if record.id == record_id:
                    self.screen.current_record = record
                    set_cursor = True
                    break
        self.screen.display(set_cursor=set_cursor)
        self.message_info()
        self.activate_save()
        return True

    def sig_action(self, widget):
        if self.buttons['action'].props.sensitive:
            self.buttons['action'].props.active = True

    def sig_print(self, widget):
        if self.buttons['print'].props.sensitive:
            self.buttons['print'].props.active = True

    def sig_print_open(self, widget):
        if self.buttons['open'].props.sensitive:
            self.buttons['open'].props.active = True

    def sig_print_email(self, widget):
        if self.buttons['email'].props.sensitive:
            self.buttons['email'].props.active = True

    def sig_relate(self, widget):
        if self.buttons['relate'].props.sensitive:
            self.buttons['relate'].props.active = True

    def sig_search(self, widget):
        search_container = self.screen.screen_container
        if hasattr(search_container, 'search_entry'):
            search_container.search_entry.grab_focus()

    def action_popup(self, widget):
        button, = widget.get_children()
        button.grab_focus()
        menu = widget._menu
        if not widget.props.active:
            menu.popdown()
            return

        def menu_position(menu):
            parent = widget.get_toplevel()
            parent_x, parent_y = parent.window.get_origin()
            widget_allocation = widget.get_allocation()
            return (
                widget_allocation.x + parent_x,
                widget_allocation.y + widget_allocation.height + parent_y,
                False
            )
        menu.show_all()
        menu.popup(None, None, menu_position, 0, 0)

    def _record_message(self, screen, signal_data):
        name = '_'
        if signal_data[0]:
            name = str(signal_data[0])
        for button_id in ('print', 'relate', 'email', 'open', 'save',
                'attach'):
            button = self.buttons[button_id]
            can_be_sensitive = getattr(button, '_can_be_sensitive', True)
            button.props.sensitive = (bool(signal_data[0])
                and can_be_sensitive)
        button_switch = self.buttons['switch']
        button_switch.props.sensitive = self.screen.number_of_views > 1

        msg = name + ' / ' + str(signal_data[1])
        if signal_data[1] < signal_data[2]:
            msg += _(' of ') + str(signal_data[2])
        self.status_label.set_text(msg)
        self.message_info()
        self.activate_save()
        self.url_entry.set_text(self.screen.get_url())

    def _record_modified(self, screen, signal_data):
        # As it is called via idle_add, the form could have been destroyed in
        # the meantime.
        if self.widget_get().props.window:
            self.activate_save()

    def _record_saved(self, screen, signal_data):
        self.activate_save()
        self.update_attachment_count()

    def modified_save(self):
        self.screen.save_tree_state()
        self.screen.current_view.set_value()
        if self.screen.modified():
            value = sur_3b(
                _('This record has been modified\n'
                    'do you want to save it ?'))
            if value == 'ok':
                return self.sig_save(None)
            if value == 'ko':
                return self.sig_reload(test_modified=False)
            return False
        return True

    def sig_close(self, widget=None):
        for dialog in self.dialogs[:]:
            dialog.destroy()
        return self.modified_save()

    def _action(self, action, atype):
        action = action.copy()
        if not self.screen.save_current():
            return
        record_id = (self.screen.current_record.id
            if self.screen.current_record else None)
        record_ids = [r.id for r in self.screen.selected_records]
        action = Action.evaluate(action, atype, self.screen.current_record)
        data = {
            'model': self.screen.model_name,
            'id': record_id,
            'ids': record_ids,
        }
        Action._exec_action(action, data, self.screen.context)

    def activate_save(self):
        self.buttons['save'].props.sensitive = self.screen.modified()

    def sig_win_close(self, widget):
        Main.get_main().sig_win_close(widget)

    def create_toolbar(self, toolbars):
        gtktoolbar = super(Form, self).create_toolbar(toolbars)

        attach_btn = self.buttons['attach']
        attach_btn.drag_dest_set(gtk.DEST_DEFAULT_ALL, [
                ('text/uri-list', 0, 0),
                ], gtk.gdk.ACTION_MOVE)
        attach_btn.connect('drag_data_received',
            self.attach_drag_data_received)

        iconstock = {
            'print': 'tryton-print',
            'action': 'tryton-executable',
            'relate': 'tryton-go-jump',
            'email': 'tryton-print-email',
            'open': 'tryton-print-open',
        }
        for action_type, special_action, action_name, tooltip in (
                ('action', 'action', _('Action'), _('Launch action')),
                ('relate', 'relate', _('Relate'), _('Open related records')),
                (None,) * 4,
                ('print', 'open', _('Report'), _('Open report')),
                ('print', 'email', _('E-Mail'), _('E-Mail report')),
                ('print', 'print', _('Print'), _('Print report')),
        ):
            if action_type is not None:
                tbutton = gtk.ToggleToolButton(iconstock.get(special_action))
                tbutton.set_label(action_name)
                tbutton._menu = self._create_popup_menu(tbutton,
                    action_type, toolbars[action_type], special_action)
                tbutton.connect('toggled', self.action_popup)
                self.tooltips.set_tip(tbutton, tooltip)
                self.buttons[special_action] = tbutton
                if action_type != 'action':
                    tbutton._can_be_sensitive = bool(
                        tbutton._menu.get_children())
            else:
                tbutton = gtk.SeparatorToolItem()
            gtktoolbar.insert(tbutton, -1)

        return gtktoolbar

    def _create_popup_menu(self, widget, keyword, actions, special_action):
        menu = gtk.Menu()
        menu.connect('deactivate', self._popup_menu_hide, widget)

        if keyword == 'action':
            widget.connect('toggled', self._update_action_popup, menu)

        for action in actions:
            new_action = action.copy()
            if special_action == 'print':
                new_action['direct_print'] = True
            elif special_action == 'email':
                new_action['email_print'] = True
            action_name = action['name']
            if '_' not in action_name:
                action_name = '_' + action_name
            menuitem = gtk.MenuItem(action_name)
            menuitem.set_use_underline(True)
            menuitem.connect('activate', self._popup_menu_selected, widget,
                new_action, keyword)
            menu.add(menuitem)
        return menu

    def _popup_menu_selected(self, menuitem, togglebutton, action, keyword):
        event = gtk.get_current_event()
        allow_similar = False
        if (event.state & gtk.gdk.CONTROL_MASK
                or event.state & gtk.gdk.MOD1_MASK):
            allow_similar = True
        with Window(hide_current=True, allow_similar=allow_similar):
            self._action(action, keyword)
        togglebutton.props.active = False

    def _popup_menu_hide(self, menuitem, togglebutton):
        togglebutton.props.active = False

    def _update_action_popup(self, tbutton, menu):
        for item in menu.get_children():
            if (getattr(item, '_update_action', False)
                    or isinstance(item, gtk.SeparatorMenuItem)):
                menu.remove(item)

        buttons = self.screen.get_buttons()
        if buttons:
            menu.add(gtk.SeparatorMenuItem())
        for button in buttons:
            menuitem = gtk.ImageMenuItem(button.attrs.get('icon'))
            menuitem.set_label('_' + button.attrs.get('string', _('Unknown')))
            menuitem.set_use_underline(True)
            menuitem.connect('activate',
                lambda m, attrs: self.screen.button(attrs), button.attrs)
            menuitem._update_action = True
            menu.add(menuitem)

        menu.add(gtk.SeparatorMenuItem())
        for plugin in plugins.MODULES:
            for name, func in plugin.get_plugins(self.model):
                menuitem = gtk.MenuItem('_' + name)
                menuitem.set_use_underline(True)
                menuitem.connect('activate', lambda m, func: func({
                            'model': self.model,
                            'ids': [r.id
                                for r in self.screen.selected_records],
                            'id': (self.screen.current_record.id
                                if self.screen.current_record else None),
                            }), func)
                menuitem._update_action = True
                menu.add(menuitem)

    def set_cursor(self):
        if self.screen:
            self.screen.set_cursor(reset_view=False)

    def attach_drag_data_received(self, widget, context, x, y, selection, info,
            timestamp):
        record = self.screen.current_record
        if not record or record.id < 0:
            return
        win_attach = Attachment(record,
            lambda: self.update_attachment_count(reload=True))
        if info == 0:
            for uri in selection.data.splitlines():
                # Win32 cut&paste terminates the list with a NULL character
                if not uri or uri == '\0':
                    continue
                win_attach.add_uri(uri)
