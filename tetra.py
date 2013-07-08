#!/usr/bin/env python

import logging

import sys
import time

import gi
gi.require_version('Gst', '1.0')

from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gst
from gi.repository import GstVideo
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkX11

import cairo

GObject.threads_init()
Gst.init(sys.argv)
Gtk.init(sys.argv)
Gdk.init(sys.argv)


from tetra_core import TetraApp, INPUT_COUNT, DEFAULT_NOISE_BASELINE
import input_sources

class MainWindow(object):
    def __init__(self, app):
        self.app = app
        self.imon = input_sources.InputMonitor()

        self.builder = Gtk.Builder ()
        self.builder.add_from_file ('main_ui_2.ui')

        self.window = self.builder.get_object('tetra_main')
        self.window.connect ("destroy", lambda app: Gtk.main_quit())
        self.window.fullscreen ()

        self.preview_box = self.builder.get_object('PreviewBox')
        self.controls = self.builder.get_object('controls')

        self.sliders = []
        self.bars = []
        self.previews = []

        self.window.show_all()

        for (src,props) in self.imon.get_devices():
            source = src(**props)
            self.add_source(source)
            self.app.add_input_source(source)

        live = self.builder.get_object('LiveOut')
        live.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.TOUCH_MASK)
        live.connect('button-press-event', self.live_click_cb)
        live.connect('draw', self.live_draw_cb)
        self.previews.append (live)

        self.builder.get_object('automatico').connect('clicked', self.auto_click_cb)

        app.vsink.set_window_handle(live.get_property('window').get_xid())

        app.connect('level', self.update_levels)
        app.connect('source-disconnected', self.source_disconnected_cb)
        self.imon.connect('added', self.source_added_cb)
        self.imon.start()

    def source_added_cb(self, imon, src, props):
        source = src(**props)
        def _add_src():
            self.add_source(source)
            self.app.add_input_source(source)
            self.app.start()
            #source.set_state(Gst.State.PLAYING)
        # XXX: FIXME: we should wait till pulseaudio releases the card.
        # (or disable it)
        GLib.timeout_add(9*1000, _add_src)

    def add_source(self, source):
        builder = Gtk.Builder ()
        builder.add_objects_from_file ('preview_box.ui', ['PreviewBoxItem'])

        slider = builder.get_object ('volume')
        slider.connect ("value-changed", self.slider_cb, source)

        bar = builder.get_object ('peak')
        self.bars.append (bar)

        mute = builder.get_object ('mute')
        mute.connect ("toggled", self.mute_cb, source)

        da = builder.get_object('preview')
        da.show()

        da.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.TOUCH_MASK)
        da.connect('button-press-event', self.preview_click_cb, source)
        self.preview_box.add(builder.get_object('PreviewBoxItem'))

        source.xvsink.set_window_handle(da.get_property('window').get_xid())

    def auto_click_cb (self, widget):
        self.app.set_automatic(widget.get_active())

    def live_draw_cb (self, widget, cr):
        return False

    def live_click_cb (self, widget, event):
        self.controls.set_visible(not self.controls.get_visible())

    def preview_click_cb (self, widget, event, source):
        self.app.set_active_input_by_source (source)

    def prepare_xwindow_id_cb (self, app, sink, idx):
        return True
        Gdk.threads_enter ()
        sink.set_property ("force-aspect-ratio", True)
        sink.set_xwindow_id (self.previews[idx].window.xid)
        Gdk.threads_leave ()

    def source_disconnected_cb (self, app, source, idx):
        try:
            child = self.preview_box.get_children()[idx]
            self.preview_box.remove(child)
            self.bars.pop(idx)
            child.destroy()
        except IndexError:
            pass
        return True

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

    def mute_cb(self, toggle, source):
        chan = self.app.inputs.index(source)
        self.app.mute_channel (chan, toggle.get_active())

    def slider_cb(self, slider, value, source):
        chan = self.app.inputs.index(source)
        self.app.set_channel_volume (chan, value)


def load_theme(theme):
    provider = Gtk.CssProvider.get_default()
    provider.load_from_path(theme)
    screen = Gdk.Screen.get_default()
    context = Gtk.StyleContext()
    context.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

if __name__ == "__main__":

    logging.basicConfig(level=logging.DEBUG)

    load_theme('theme-tetra-ambiance/gtk.css')
    app = TetraApp()

    w2 = MainWindow(app)

    app.start()

    Gst.debug_bin_to_dot_file(app.pipeline, Gst.DebugGraphDetails.NON_DEFAULT_PARAMS | Gst.DebugGraphDetails.MEDIA_TYPE , 'debug_start')

    Gtk.main()
    sys.exit(0)

