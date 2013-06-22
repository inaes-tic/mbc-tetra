#!/usr/bin/env python

import sys
import time
from collections import deque
from itertools import ifilter

import gobject
import gst
import glib
import gtk

gobject.threads_init()
gtk.gdk.threads_init()


class AppWindow():
    def __init__ (self):
        self.builder = gtk.Builder ()
        self.builder.add_from_file ('main_ui.glade')

        self.window = self.builder.get_object('tetra_main')
        self.window.connect ("destroy", lambda app: gtk.main_quit())

        self.volume_box = self.builder.get_object('volume_controls')
        for idx in range(3):
            builder = gtk.Builder ()
            builder.add_objects_from_file('volume_control.glade', ['volume_control', 'volume_adj'])
            vc = builder.get_object ('volume_control')
            self.volume_box.add (vc)

        self.window.show_all ()
        #self.window.fullscreen ()

        self.live_out = self.builder.get_object('LiveOut')
        self.live_out.set_property ('width-request', 640)

        video_pipeline = "v4l2src device=/dev/video0 ! video/x-raw-yuv,width=640,height=480,framerate=30/1 ! xvimagesink"
        self.video_player = gst.parse_launch(video_pipeline) # create pipeline

        bus = self.video_player.get_bus()
        bus.add_signal_watch()
        #bus.connect("message", self.on_message)
        bus.enable_sync_message_emission()
        bus.connect("sync-message::element", self.on_sync_message)

        self.window.show_all()

        self.video_player.set_state(gst.STATE_PLAYING)       # start video stream

    def on_sync_message(self, bus, message):
        """ Set up the Webcam <--> GUI messages bus """
        if message.structure is None:
            return
        message_name = message.structure.get_name()
        if message_name == "prepare-xwindow-id":
            # Assign the viewport
            imagesink = message.src
            imagesink.set_property("force-aspect-ratio", True)
            gtk.gdk.threads_enter ()
            imagesink.set_xwindow_id(self.live_out.window.xid) # Sending video stream to gtk DrawingArea
            gtk.gdk.threads_leave ()

if __name__ == "__main__":
    app = AppWindow()


    gtk.main()
