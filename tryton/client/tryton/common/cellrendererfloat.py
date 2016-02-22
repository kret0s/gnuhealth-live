# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
import gtk
import gobject
import locale
from cellrendererinteger import CellRendererInteger


class CellRendererFloat(CellRendererInteger):

    def __init__(self):
        super(CellRendererFloat, self).__init__()
        self.digits = None

    def do_start_editing(self, event, widget, path, background_area,
            cell_area, flags):
        editable = super(CellRendererFloat, self).do_start_editing(event,
            widget, path, background_area, cell_area, flags)
        editable.connect('key-press-event', self.key_press_event)
        return editable

    def key_press_event(self, widget, event):
        for name in ('KP_Decimal', 'KP_Separator'):
            if event.keyval == gtk.gdk.keyval_from_name(name):
                event.keyval = int(gtk.gdk.unicode_to_keyval(
                    ord(locale.localeconv()['decimal_point'])))

    def sig_insert_text(self, entry, new_text, new_text_length, position):
        value = entry.get_text()
        position = entry.get_position()
        new_value = value[:position] + new_text + value[position:]
        decimal_point = locale.localeconv()['decimal_point']

        if new_value in ('-', decimal_point):
            return

        try:
            locale.atof(new_value)
        except ValueError:
            entry.stop_emission('insert-text')
            return

        new_int = new_value
        new_decimal = ''
        if decimal_point in new_value:
            new_int, new_decimal = new_value.rsplit(decimal_point, 1)

        if (self.digits
                and (len(new_int) > self.digits[0]
                    or len(new_decimal) > self.digits[1])):
            entry.stop_emission('insert-text')


gobject.type_register(CellRendererFloat)
