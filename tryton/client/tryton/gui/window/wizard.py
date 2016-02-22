# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import gtk
import pango
import gettext

from tryton.signal_event import SignalEvent
import tryton.common as common
from tryton.gui.window.view_form.screen import Screen
from tryton.gui import Main
from tryton.exceptions import TrytonServerError
from tryton.gui.window.nomodal import NoModal
from tryton.common.button import Button
from tryton.common import RPCExecute, RPCException
from tryton.common import TRYTON_ICON
from .infobar import InfoBar
_ = gettext.gettext


class Wizard(InfoBar):

    def __init__(self, name=False):
        super(Wizard, self).__init__()
        self.widget = gtk.VBox(spacing=3)
        self.toolbar_box = None
        self.widget.show()
        self.name = name or ''
        self.id = None
        self.ids = None
        self.action = None
        self.action_id = None
        self.direct_print = False
        self.email_print = False
        self.email = False
        self.context = None
        self.states = {}
        self.response2state = {}
        self.__processing = False
        self.__waiting_response = False
        self.session_id = None
        self.start_state = None
        self.end_state = None
        self.screen = None
        self.screen_state = None
        self.state = None

    def run(self, action, data, direct_print=False, email_print=False,
            email=None, context=None):
        self.action = action
        self.action_id = data.get('action_id')
        self.id = data.get('id')
        self.ids = data.get('ids')
        self.model = data.get('model')
        self.direct_print = direct_print
        self.email_print = email_print
        self.email = email
        self.context = context

        def callback(result):
            try:
                result = result()
            except RPCException:
                return
            self.session_id, self.start_state, self.end_state = result
            self.state = self.start_state
            self.process()
        RPCExecute('wizard', action, 'create', callback=callback)

    def process(self):
        from tryton.action import Action
        if self.__processing or self.__waiting_response:
            return
        self.__processing = True

        ctx = self.context.copy()
        ctx['active_id'] = self.id
        ctx['active_ids'] = self.ids
        ctx['active_model'] = self.model
        ctx['action_id'] = self.action_id
        if self.screen:
            data = {
                self.screen_state: self.screen.get_on_change_value(),
                }
        else:
            data = {}

        def callback(result):
            try:
                result = result()
            except RPCException, rpc_exception:
                if (not isinstance(rpc_exception.exception,
                        TrytonServerError)
                        or not self.screen):
                    self.state = self.end_state
                    self.end()
                self.__processing = False
                return

            if 'view' in result:
                self.clean()
                view = result['view']
                self.update(view['fields_view'], view['defaults'],
                    view['buttons'])
                self.screen_state = view['state']
                self.__waiting_response = True
            else:
                self.state = self.end_state

            def execute_actions():
                for action in result.get('actions', []):
                    for k, v in [
                            ('direct_print', self.direct_print),
                            ('email_print', self.email_print),
                            ('email', self.email),
                            ]:
                        action[0].setdefault(k, v)
                    Action._exec_action(*action, context=self.context.copy())

            if self.state == self.end_state:
                self.end(lambda *a: execute_actions())
            else:
                execute_actions()
            self.__processing = False

        RPCExecute('wizard', self.action, 'execute', self.session_id, data,
            self.state, context=ctx, callback=callback)

    def destroy(self):
        if self.screen:
            self.screen.destroy()

    def end(self, callback=None):
        RPCExecute('wizard', self.action, 'delete', self.session_id,
            process_exception=False, callback=callback)

    def clean(self):
        for widget in self.widget.get_children():
            self.widget.remove(widget)
        self.states = {}

    def response(self, widget, response):
        self.__waiting_response = False
        state = self.response2state.get(response, self.end_state)
        self.screen.current_view.set_value()
        if (not self.screen.current_record.validate()
                and state != self.end_state):
            self.screen.display(set_cursor=True)
            self.message_info(self.screen.invalid_message(), gtk.MESSAGE_ERROR)
            return
        self.message_info()
        self.state = state
        self.process()

    def _get_button(self, definition):
        button = Button(definition)
        self.states[definition['state']] = button
        response = len(self.states)
        self.response2state[response] = definition['state']
        button.show()
        return button

    def _record_modified(self, screen, record):
        self.update_buttons(record)

    def update_buttons(self, record):
        for button in self.states.itervalues():
            button.state_set(record)

    def update(self, view, defaults, buttons):
        for button in buttons:
            self._get_button(button)

        self.screen = Screen(view['model'], mode=[], context=self.context)
        self.screen.add_view(view)
        self.screen.switch_view()
        self.screen.widget.show()
        self.screen.signal_connect(self, 'record-modified',
            self._record_modified)

        title = gtk.Label()
        title.modify_font(pango.FontDescription("bold 14"))
        title.set_label(self.screen.current_view.title)
        title.set_padding(20, 4)
        title.set_alignment(0.0, 0.5)
        title.set_size_request(0, -1)  # Allow overflow
        title.modify_fg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#000000"))
        title.show()

        hbox = gtk.HBox()
        hbox.pack_start(title, expand=True, fill=True)
        hbox.show()

        frame = gtk.Frame()
        frame.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        frame.add(hbox)
        frame.show()

        eb = gtk.EventBox()
        eb.add(frame)
        eb.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#ffffff"))
        eb.show()

        self.widget.pack_start(eb, expand=False, fill=True, padding=3)

        self.create_info_bar()
        self.widget.pack_start(self.info_bar, False, True)

        if self.toolbar_box:
            self.widget.pack_start(self.toolbar_box, False, True)

        viewport = gtk.Viewport()
        viewport.set_shadow_type(gtk.SHADOW_NONE)
        viewport.add(self.screen.widget)
        viewport.show()
        self.scrolledwindow = gtk.ScrolledWindow()
        self.scrolledwindow.set_shadow_type(gtk.SHADOW_NONE)
        self.scrolledwindow.set_policy(gtk.POLICY_AUTOMATIC,
                gtk.POLICY_AUTOMATIC)
        self.scrolledwindow.add(viewport)
        self.scrolledwindow.show()

        self.widget.pack_start(self.scrolledwindow)

        self.screen.new(default=False)
        self.screen.current_record.set_default(defaults)
        self.update_buttons(self.screen.current_record)
        self.screen.set_cursor()


class WizardForm(Wizard, SignalEvent):
    "Wizard"

    def __init__(self, name=False):
        super(WizardForm, self).__init__(name=name)
        self.toolbar_box = gtk.HBox()
        self.hbuttonbox = gtk.HButtonBox()
        self.hbuttonbox.set_spacing(5)
        self.hbuttonbox.set_layout(gtk.BUTTONBOX_END)
        self.hbuttonbox.show()
        self.widget.pack_start(self.toolbar_box, False, True)
        self.dialogs = []

        self.handlers = {
            'but_close': self.sig_close
        }

    def clean(self):
        super(WizardForm, self).clean()
        for button in self.hbuttonbox.get_children():
            self.hbuttonbox.remove(button)

    def _get_button(self, state):
        button = super(WizardForm, self)._get_button(state)
        response = len(self.states)
        button.connect('clicked', self.response, response)
        self.hbuttonbox.pack_start(button)
        return button

    def update(self, view, defaults, buttons):
        super(WizardForm, self).update(view, defaults, buttons)
        self.widget.pack_start(self.hbuttonbox, expand=False, fill=True)

    def sig_close(self):
        if self.end_state in self.states:
            self.states[self.end_state].clicked()
        return self.state == self.end_state

    def destroy(self):
        if self.toolbar_box.get_children():
            toolbar = self.toolbar_box.get_children()[0]
            self.toolbar_box.remove(toolbar)
        super(WizardForm, self).destroy()

    def end(self, callback=None):
        super(WizardForm, self).end(callback=callback)
        Main.get_main()._win_del(self.widget)

    def set_cursor(self):
        if self.screen:
            self.screen.set_cursor()


class WizardDialog(Wizard, NoModal):

    def __init__(self, name=False):
        if not name:
            name = _('Wizard')
        Wizard.__init__(self, name=name)
        NoModal.__init__(self)
        self.dia = gtk.Dialog(self.name, self.parent,
            gtk.DIALOG_DESTROY_WITH_PARENT)
        self.dia.set_position(gtk.WIN_POS_CENTER_ON_PARENT)
        self.dia.set_icon(TRYTON_ICON)
        self.dia.set_deletable(False)
        self.dia.connect('close', self.close)
        self.dia.connect('response', self.response)

        self.accel_group = gtk.AccelGroup()
        self.dia.add_accel_group(self.accel_group)

        self.dia.vbox.add(self.widget)

        self.register()

    def clean(self):
        super(WizardDialog, self).clean()
        hbuttonbox = self.dia.get_action_area()
        for button in hbuttonbox.get_children():
            hbuttonbox.remove(button)

    def _get_button(self, definition):
        button = super(WizardDialog, self)._get_button(definition)
        response = len(self.states)
        self.dia.add_action_widget(button, response)
        if definition['default']:
            button.set_flags(gtk.CAN_DEFAULT)
            button.add_accelerator('clicked', self.accel_group,
                gtk.keysyms.Return, gtk.gdk.CONTROL_MASK,
                gtk.ACCEL_VISIBLE)
            self.dia.set_default_response(response)
        return button

    def update(self, view, defaults, buttons):
        super(WizardDialog, self).update(view, defaults, buttons)
        sensible_allocation = self.sensible_widget.get_allocation()
        self.dia.set_default_size(int(sensible_allocation.width * 0.9),
            int(sensible_allocation.height * 0.9))
        self.dia.show()
        common.center_window(self.dia, self.parent, self.sensible_widget)

    def destroy(self, action=None):
        super(WizardDialog, self).destroy()
        self.dia.destroy()
        NoModal.destroy(self)
        main = Main.get_main()
        if self.parent == main.window:
            current_form = main.get_page()
            if current_form:
                for dialog in current_form.dialogs:
                    dialog.show()
        if self.page.dialogs:
            dialog = self.page.dialogs[-1]
        else:
            dialog = self.page
        screen = getattr(dialog, 'screen', None)
        if self.sensible_widget == main.window:
            screen = main.menu_screen
        if screen:
            if (screen.current_record
                    and self.sensible_widget != main.window):
                if screen.model_name == self.model:
                    ids = self.ids
                else:
                    # Wizard run from a children record so reload parent record
                    ids = [screen.current_record.id]
                screen.reload(ids, written=True)
            if action:
                screen.client_action(action)

    def end(self, callback=None):
        def end_callback(action):
            self.destroy(action=action())
            if callback:
                callback()
        super(WizardDialog, self).end(callback=end_callback)

    def close(self, widget, event=None):
        widget.emit_stop_by_name('close')
        if self.end_state in self.states:
            self.states[self.end_state].clicked()
        return True

    def show(self):
        self.dia.show()

    def hide(self):
        self.dia.hide()
