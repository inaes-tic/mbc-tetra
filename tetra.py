#!/usr/bin/env python

import sys
import time

import gobject
import gst
import glib
import gtk

gobject.threads_init()
gtk.gdk.threads_init()

from tetra_core import TetraApp, INPUT_COUNT, DEFAULT_NOISE_BASELINE

class MainWindow(object):
    def __init__(self, app):
        self.app = app

        self.builder = gtk.Builder ()
        self.builder.add_from_file ('main_ui_2.glade')

        self.window = self.builder.get_object('tetra_main')
        self.window.connect ("destroy", lambda app: gtk.main_quit())
        self.window.fullscreen ()

        self.volume_box = self.builder.get_object('volume_controls')
        self.preview_box = self.builder.get_object('PreviewBox')

        self.builder.get_object ('calibrate_bg_noise').connect ('clicked', self.app.calibrate_bg_noise)

        sliders = []
        bars = []
        previews = []
        for idx in range(INPUT_COUNT):
            builder = gtk.Builder ()
            builder.add_objects_from_file ('volume_control.glade', ['volume_control', 'volume_adj'])
            vc = builder.get_object ('volume_control')
            self.volume_box.add (vc)

            slider = builder.get_object ('volume')
            slider.connect ("value-changed", self.slider_cb, idx)
            sliders.append (slider)

            bar = builder.get_object ('peak')
            bars.append (bar)

            mute = builder.get_object ('mute')
            mute.connect ("toggled", self.mute_cb, idx)

            da = gtk.DrawingArea ()
## XXX
            da.add_events(gtk.gdk.BUTTON_PRESS_MASK)
            da.connect('button-press-event', self.preview_click_cb, idx)
            da.set_property ('height-request', 240)
            da.set_property ('width-request', 320)
            self.preview_box.add (da)
            previews.append (da)


        self.previews = previews
        self.previews.append (self.builder.get_object('LiveOut'))
        self.sliders = sliders
        self.bars = bars

        app.connect('level', self.update_levels)
        app.connect('prepare-xwindow-id', self.prepare_xwindow_id_cb)

    def preview_click_cb (self, widget, event, idx):
        self.app.set_active_input (idx)

    def prepare_xwindow_id_cb (self, app, sink, idx):
        gtk.gdk.threads_enter ()
        sink.set_property ("force-aspect-ratio", True)
        sink.set_xwindow_id (self.previews[idx].window.xid)
        gtk.gdk.threads_leave ()

    def update_levels (self, app, idx, peak):
        gtk.gdk.threads_enter ()
        frac = 1.0 - peak/DEFAULT_NOISE_BASELINE
        if frac < 0:
            frac = 0
        elif frac > 1:
            frac = 1
        self.bars[idx].set_fraction (frac)
        gtk.gdk.threads_leave ()
        return True

    def mute_cb(self, toggle, chan):
        self.app.mute_channel (chan, toggle.get_active())

    def slider_cb(self, slider, chan):
        self.app.set_channel_volume (chan, slider.get_value()/100.0)


if __name__ == "__main__":

    #gtk.rc_parse('./theme_tetra.gtkrc')
    #gtk.rc_parse('melissablue/gtkrc')
    gtk.rc_parse('diehard4/gtkrc')
    app = TetraApp()

    w2 = MainWindow(app)
    w2.window.show_all()

    app.start()
    #gst.DEBUG_BIN_TO_DOT_FILE(app.pipeline, gst.DEBUG_GRAPH_SHOW_NON_DEFAULT_PARAMS | gst.DEBUG_GRAPH_SHOW_MEDIA_TYPE , 'debug1')
    gst.DEBUG_BIN_TO_DOT_FILE(app.pipeline, gst.DEBUG_GRAPH_SHOW_NON_DEFAULT_PARAMS | gst.DEBUG_GRAPH_SHOW_MEDIA_TYPE | gst.DEBUG_GRAPH_SHOW_CAPS_DETAILS, 'debug1')

    gtk.main()
    sys.exit(0)

