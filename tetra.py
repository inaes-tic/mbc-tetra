#!/usr/bin/env python

import sys
import time

import gi
gi.require_version('Gst', '1.0')

from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstVideo
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkX11

GObject.threads_init()
Gst.init(sys.argv)
Gtk.init(sys.argv)
Gdk.init(sys.argv)


from tetra_core import TetraApp, INPUT_COUNT, DEFAULT_NOISE_BASELINE

class MainWindow(object):
    def __init__(self, app):
        self.app = app

        self.builder = Gtk.Builder ()
        self.builder.add_from_file ('main_ui_2.ui')

        self.window = self.builder.get_object('tetra_main')
        self.window.connect ("destroy", lambda app: Gtk.main_quit())
        self.window.fullscreen ()

        self.preview_box = self.builder.get_object('PreviewBox')

        sliders = []
        bars = []
        previews = []

        for idx in range(INPUT_COUNT):
            builder = Gtk.Builder ()
            builder.add_objects_from_file ('preview_box.ui', ['PreviewBoxItem'])

            slider = builder.get_object ('volume')
            slider.connect ("value-changed", self.slider_cb, idx)
            sliders.append (slider)

            bar = builder.get_object ('peak')
            bars.append (bar)

            mute = builder.get_object ('mute')
            mute.connect ("toggled", self.mute_cb, idx)

            da = builder.get_object('preview')
## XXX
            da.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.TOUCH_MASK)
            da.connect('button-press-event', self.preview_click_cb, idx)
##             da.set_property ('height-request', 240)
##             da.set_property ('width-request', 320)
            previews.append (da)
            self.preview_box.add(builder.get_object('PreviewBoxItem'))


        self.previews = previews
        self.previews.append (self.builder.get_object('LiveOut'))
        self.sliders = sliders
        self.bars = bars

        self.window.show_all()

        for da, sink in zip(previews, app.preview_sinks):
            sink.set_window_handle(da.get_property('window').get_xid())

        app.connect('level', self.update_levels)

    def preview_click_cb (self, widget, event, idx):
        print 'PREVIEW CLICK idx ', idx
        self.app.set_active_input (idx)

    def prepare_xwindow_id_cb (self, app, sink, idx):
        return True
        Gdk.threads_enter ()
        sink.set_property ("force-aspect-ratio", True)
        sink.set_xwindow_id (self.previews[idx].window.xid)
        Gdk.threads_leave ()

    def update_levels (self, app, idx, peak):
        Gdk.threads_enter ()
        frac = 1.0 - peak/DEFAULT_NOISE_BASELINE
        if frac < 0:
            frac = 0
        elif frac > 1:
            frac = 1
        self.bars[idx].set_fraction (frac)
        Gdk.threads_leave ()
        return True

    def mute_cb(self, toggle, chan):
        self.app.mute_channel (chan, toggle.get_active())

    def slider_cb(self, slider, value, chan):
        self.app.set_channel_volume (chan, value)


def load_theme(theme):
    provider = Gtk.CssProvider.get_default()
    provider.load_from_path(theme)
    screen = Gdk.Screen.get_default()
    context = Gtk.StyleContext()
    context.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

if __name__ == "__main__":

    app = TetraApp()

    w2 = MainWindow(app)

    app.start()

    Gst.debug_bin_to_dot_file(app.pipeline, Gst.DebugGraphDetails.NON_DEFAULT_PARAMS | Gst.DebugGraphDetails.MEDIA_TYPE , 'debug1')

    Gtk.main()
    sys.exit(0)

