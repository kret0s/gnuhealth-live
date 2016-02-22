# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import gtk
import gobject


class CellRendererToggle(gtk.CellRendererToggle):

    def set_sensitive(self, value):
        self.set_property('sensitive', value)

    def do_activate(self, event, widget, path, background_area, cell_area,
            flags):
        if not self.props.visible:
            return
        if not event:
            event = gtk.gdk.Event(gtk.keysyms.KP_Space)
        return gtk.CellRendererToggle.do_activate(self, event, widget, path,
            background_area, cell_area, flags)

    def do_start_editing(self, event, widget, path, background_area,
            cell_area, flags):
        if not self.props.visible:
            return
        return gtk.CellRendererToggle.do_start_editing(self, event, widget,
            path, background_area, cell_area, flags)

gobject.type_register(CellRendererToggle)
