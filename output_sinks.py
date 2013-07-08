#!/usr/bin/env python

import logging

import time
import sys
import os
from collections import deque
from itertools import ifilter

import pyudev

import gi
gi.require_version('Gst', '1.0')

from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstVideo
from gi.repository import GLib

if not Gst.is_initialized():
    Gst.init(sys.argv)

from common import *

class AutoOutput(Gst.Bin):
    def __init__(self, name=None):
        Gst.Bin.__init__(self)
        if name:
            self.set_property('name', name)

        self.aq = Gst.ElementFactory.make('queue2', 'audio q')
        self.vq = Gst.ElementFactory.make('queue2', 'video q')

        self.asink = Gst.ElementFactory.make('autoaudiosink', 'audio sink')
        self.vsink = Gst.ElementFactory.make('xvimagesink', 'video sink')
        self.preview_sink = self.vsink

        for el in [self.aq, self.vq, self.asink, self.vsink]:
            self.add(el)

        self.aq.link(self.asink)

        caps = Gst.Caps.from_string ('video/x-raw,width=%d,heigth=%d,framerate=30/1' % (VIDEO_WIDTH, VIDEO_HEIGTH))
        self.vq.link_filtered(self.vsink, caps)

        agpad = Gst.GhostPad.new('audiosink', self.aq.get_static_pad('sink'))
        vgpad = Gst.GhostPad.new('videosink', self.vq.get_static_pad('sink'))

        self.add_pad(vgpad)
        self.add_pad(agpad)

    def __contains__ (self, item):
        return item in self.children

    def initialize(self):
        self.preview_sink.set_property('sync', XV_SYNC)

class MP4Output(Gst.Bin):
    def __init__(self, name=None):
        Gst.Bin.__init__(self)
        if name:
            self.set_property('name', name)

        aq = Gst.ElementFactory.make('queue2', 'audio q')
        vq = Gst.ElementFactory.make('queue2', 'video q')
        self.preview_sink = None

        aenc = Gst.ElementFactory.make('avenc_aac', None)

        vsink = Gst.ElementFactory.make ('tcpserversink', None)
        vsink.set_property('host', '127.0.0.1')
        vsink.set_property('port', 9078)
        vmux = Gst.ElementFactory.make ('mp4mux', None)
        vmux.set_property('streamable', True)
        vmux.set_property('fragment-duration', 100)
        vmux.set_property('dts-method', 2) # ascending


        parser = Gst.ElementFactory.make ('h264parse', None)
        parser.set_property ('config-interval',2)

        venc = Gst.ElementFactory.make ('x264enc', None)
        venc.set_property('tune', 'zerolatency')
        venc.set_property('speed-preset', 'ultrafast')
        venc.set_property ('key-int-max',15)
        venc.set_property ('bitrate',1024)

        for el in [aq, vq, aenc, venc, parser, vmux, vsink]:
            self.add(el)

        aq.link(aenc)
        aenc.link(vmux)

        caps = Gst.Caps.from_string ('video/x-raw,width=%d,heigth=%d,framerate=30/1' % (VIDEO_WIDTH, VIDEO_HEIGTH))
        vq.link_filtered(venc, caps)

        venc.link(parser)
        parser.link(vmux)
        vmux.link(vsink)


        agpad = Gst.GhostPad.new('audiosink', aq.get_static_pad('sink'))
        vgpad = Gst.GhostPad.new('videosink', vq.get_static_pad('sink'))

        self.add_pad(vgpad)
        self.add_pad(agpad)

    def __contains__ (self, item):
        return item in self.children

    def initialize(self):
        pass

