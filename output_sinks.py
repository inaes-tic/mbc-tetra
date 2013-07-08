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

