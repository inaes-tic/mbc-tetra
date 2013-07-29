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

import config
from common import *

from tetra_core import TetraApp, INPUT_COUNT, DEFAULT_NOISE_BASELINE
from widgets import SoundMixWidget, PreviewWidget, MasterMonitor
import input_sources

class MainWindow(object):
    def __init__(self, app):
        self.app = app
        self.imon = input_sources.InputMonitor()

        self.builder = Gtk.Builder ()
        self.builder.add_from_file (config.get('main_ui', 'main_ui_2.ui'))

        self.window = self.builder.get_object('tetra_main')
        self.window.connect ("destroy", lambda app: Gtk.main_quit())
        self.window.fullscreen ()

        self.preview_box = self.builder.get_object('PreviewBox')
        self.main_box = self.builder.get_object('MainBox')
        self.controls = self.builder.get_object('controls')
        self.options_box = self.builder.get_object('OptionsBox')

        self.sound_mix = SoundMixWidget()
        self.options_box.add(self.sound_mix)
        self.sound_mix.connect('set-mix-device', self.insert_sel_cb)
        self.sound_mix.connect('set-mix-source', self.insert_sel_cb)
        self.insert_sel_cb(self.sound_mix, None)

        self.master_monitor = MasterMonitor()
        self.main_box.add(self.master_monitor)

        self.sliders = []
        self.bars = []
        self.previews = {}

        self.window.show_all()

        for (src,props) in self.imon.get_devices():
            source = src(**props)
            self.add_source(source)
            self.app.add_input_source(source)

        live = self.builder.get_object('LiveOut')
        self.live = live
        self.live_xid = live.get_property('window').get_xid()
        live.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.TOUCH_MASK)
        live.connect('button-press-event', self.live_click_cb)
        #live.connect('draw', self.live_draw_cb)

        self.builder.get_object('automatico').connect('clicked', self.auto_click_cb)

        app.live_sink.set_window_handle(live.get_property('window').get_xid())

        app.connect('level', self.update_levels)
        app.connect('master-level', self.update_master_level)
        app.connect('source-disconnected', self.source_disconnected_cb)
        app.connect('prepare-window-handle', self.prepare_window_handle_cb)
        self.imon.connect('added', self.source_added_cb)
        self.imon.start()

    def source_added_cb(self, imon, src, props):
        source = src(**props)
        preview = self.add_source()
        def _add_src():
            self.previews[source] = preview
            preview.set_source(source)
            self.app.add_input_source(source)
            self.app.live_sink.set_property('sync', XV_SYNC)
            self.app.start()
            Gst.debug_bin_to_dot_file(app.pipeline, Gst.DebugGraphDetails.NON_DEFAULT_PARAMS | Gst.DebugGraphDetails.MEDIA_TYPE | Gst.DebugGraphDetails.CAPS_DETAILS , 'source_added_cb')
        # XXX: FIXME: we should wait till pulseaudio releases the card.
        # (or disable it)
        GLib.timeout_add(9*1000, _add_src)

    def add_source(self, source=None):
        preview = PreviewWidget(source)
        self.preview_box.add(preview)
        preview.show()
        self.previews[source] = preview
        preview.connect('preview-clicked', self.preview_click_cb)
        return preview

    def insert_sel_cb (self, widget, arg):
        source = widget.mix_source
        devinfo = widget.mix_device
        device = devinfo['device']
        if source == 'external':
            if not self.app.audio_inserts:
                src = input_sources.AlsaInput({'device': device})
                self.app.add_audio_insert(src)
            else:
                self.app.audio_inserts[0].set_device(device)
        self.app.set_audio_source(source)

    def auto_click_cb (self, widget):
        self.app.set_automatic(widget.get_active())

    def live_draw_cb (self, widget, cr):
        return False

    def live_click_cb (self, widget, event):
        self.controls.set_visible(not self.controls.get_visible())

    def preview_click_cb (self, widget, source):
        self.app.set_active_input_by_source (source)

    def prepare_window_handle_cb (self, app, xvimagesink, source):
        if source in self.previews:
            logging.debug('prepare window handle %s', source)
            self.previews[source].set_window_handle()
            return True
        elif xvimagesink is self.app.live_sink:
            Gdk.threads_enter ()
            xvimagesink.set_window_handle(self.live_xid)
            xvimagesink.set_property('sync', XV_SYNC)
            Gdk.threads_leave ()

    def source_disconnected_cb (self, app, source):
        if source in self.previews:
            preview = self.previews[source]
            self.preview_box.remove(preview)
            preview.destroy()
        return True

    def update_master_level (self, app, peaks):
        self.master_monitor.set_levels(peaks)

    def update_levels (self, app, source, peaks):
        if source in self.previews:
            self.previews[source].set_levels(peaks)


def load_theme(theme_name):
    dark = config.get('use_dark_theme', False)
    provider = None
    if dark:
        provider = Gtk.CssProvider.get_named(theme_name, 'dark') or Gtk.CssProvider.get_named(theme_name, None)
    else:
        provider = Gtk.CssProvider.get_named(theme_name, None)

    if provider is None:
        logging.error('Cannot load theme: %s', theme_name)
        return

    screen = Gdk.Screen.get_default()
    context = Gtk.StyleContext()
    context.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

if __name__ == "__main__":

    logging.basicConfig(level=logging.DEBUG)


    theme = config.get('theme', None)
    if theme:
        load_theme(theme)

    app = TetraApp()

    w2 = MainWindow(app)

    app.start()

    Gst.debug_bin_to_dot_file(app.pipeline, Gst.DebugGraphDetails.NON_DEFAULT_PARAMS | Gst.DebugGraphDetails.MEDIA_TYPE | Gst.DebugGraphDetails.CAPS_DETAILS , 'debug_start')

    Gtk.main()
    sys.exit(0)

