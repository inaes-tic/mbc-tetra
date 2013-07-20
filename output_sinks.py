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
import config

class BaseOutput(Gst.Bin):
    def __init__(self):
        Gst.Bin.__init__(self)

    def __contains__ (self, item):
        return item in self.children

    def initialize(self):
        pass

    def start_file_recording(self, location=None):
        pass

    def stop_file_recording():
        pass


class AutoOutput(BaseOutput):
    def __init__(self, name=None):
        BaseOutput.__init__(self)
        if name:
            self.set_property('name', name)

        self.aq = Gst.ElementFactory.make('queue2', 'audio q')
        self.vq = Gst.ElementFactory.make('queue2', 'video q')

        self.asink = Gst.ElementFactory.make('autoaudiosink', 'audio sink')
        self.vsink = Gst.ElementFactory.make('xvimagesink', 'video sink')
        self.vsink.set_property('draw-borders', False)
        self.preview_sink = self.vsink

        for el in [self.aq, self.vq, self.asink, self.vsink]:
            self.add(el)

        self.aq.link(self.asink)

        self.vq.link_filtered(self.vsink, VIDEO_CAPS_SIZE)

        agpad = Gst.GhostPad.new('audiosink', self.aq.get_static_pad('sink'))
        vgpad = Gst.GhostPad.new('videosink', self.vq.get_static_pad('sink'))

        self.add_pad(vgpad)
        self.add_pad(agpad)

    def initialize(self):
        self.preview_sink.set_property('sync', XV_SYNC)


class MP4Output(BaseOutput):
    def __init__(self, name=None):
        BaseOutput.__init__(self)
        if name:
            self.set_property('name', name)

        conf = config.get('MP4Output', {})
        self.conf = conf

        aq = Gst.ElementFactory.make('queue2', 'audio q')
        vq = Gst.ElementFactory.make('queue2', 'video q')
        vmuxoq = Gst.ElementFactory.make('queue2', 'video mux out q')
        vmuxviq = Gst.ElementFactory.make('queue2', 'video mux video in q')
        vmuxaiq = Gst.ElementFactory.make('queue2', 'video mux audio in q')
        self.preview_sink = None

        aenc = Gst.ElementFactory.make('avenc_aac', None)

        vsink = Gst.ElementFactory.make ('tcpserversink', None)
        # remember to change them in the streaming server if you
        # stray away from the defaults
        vsink.set_property('host', conf.get('host', '127.0.0.1'))
        vsink.set_property('port', conf.get('port', 9078))

        vmux = self.make_mp4mux()

        parser = Gst.ElementFactory.make ('h264parse', None)
        parser.set_property ('config-interval',2)

        venc = Gst.ElementFactory.make ('x264enc', None)
        venc.set_property('byte-stream', True)
        venc.set_property('tune', 'zerolatency')
        # it gives unicode but x264enc wants str
        venc.set_property('speed-preset', str(conf.get('x264_speed_preset', 'ultrafast')))
        # while it might be usefull to avoid showing artifacts for a while
        # touching it plays havoc with mp4mux and the default reorder method.
        # https://bugzilla.gnome.org/show_bug.cgi?id=631855
        # Just saying, so I don't forget it in the future.
        # It lowers the compression ratio but gives a stable image faster.
        venc.set_property ('key-int-max',30)

        # these two are (supposedly) needed to avoid getting out of order
        # timestamps. We need them even if we don't use the reorder method
        # because otherwise the audio will lag.
        # (it still does a little but is hard to notice).
        venc.set_property('b-adapt', False)
        venc.set_property('bframes', 0)

        venc.set_property ('bitrate', conf.get('x264_bitrate', 1024))

        aenct = Gst.ElementFactory.make('tee', 'audio enc t')
        venct = Gst.ElementFactory.make('tee', 'video enc t')
        self.aenct = aenct
        self.venct = venct

        for el in [aq, vq, aenc, venc, aenct, venct, parser, vmux, vmuxoq, vmuxviq, vmuxaiq, vsink]:
            self.add(el)

        aq.link(aenc)
        aenc.link(aenct)
        aenct.link(vmuxaiq)
        vmuxaiq.link(vmux)

        vq.link_filtered(venc, VIDEO_CAPS_SIZE)

        venc.link(parser)
        parser.link(venct)
        venct.link(vmuxviq)
        vmuxviq.link(vmux)
        vmux.link(vmuxoq)
        vmuxoq.link(vsink)


        agpad = Gst.GhostPad.new('audiosink', aq.get_static_pad('sink'))
        vgpad = Gst.GhostPad.new('videosink', vq.get_static_pad('sink'))

        self.add_pad(vgpad)
        self.add_pad(agpad)

    def make_mp4mux(self):
        vmux = Gst.ElementFactory.make ('mp4mux', None)
        vmux.set_property('streamable', True)
        vmux.set_property('fragment-duration', 1000)

        # the default (reorder) gives a nicer and faster a/v sync
        # but x264 produces frames with  DTS timestamp and that doesn't need
        # to be always increasing. So mp4mux is not happy, see gstqtmux.c around
        # line 2800.
        vmux.set_property('dts-method', 2) # ascending

        vmux.set_property('streamable', True)
        return vmux


class FLVOutput(BaseOutput):
    def __init__(self, name=None):
        BaseOutput.__init__(self)
        if name:
            self.set_property('name', name)

        conf = config.get('FLVOutput', {})

        aq = Gst.ElementFactory.make('queue2', 'audio q')
        vq = Gst.ElementFactory.make('queue2', 'video q')
        vmuxoq = Gst.ElementFactory.make('queue2', 'video mux out q')
        vmuxviq = Gst.ElementFactory.make('queue2', 'video mux video in q')
        self.preview_sink = None

        aenc = Gst.ElementFactory.make('avenc_aac', None)

        vsink = Gst.ElementFactory.make ('tcpserversink', None)
        # remember to change them in the streaming server if you
        # stray away from the defaults
        vsink.set_property('host', conf.get('host', '127.0.0.1'))
        vsink.set_property('port', conf.get('port', 9078))

        vmux = Gst.ElementFactory.make ('flvmux', None)
        vmux.set_property('streamable', True)

        parser = Gst.ElementFactory.make ('h264parse', None)
        parser.set_property ('config-interval',2)

        venc = Gst.ElementFactory.make ('x264enc', None)
        venc.set_property('byte-stream', True)
        venc.set_property('tune', 'zerolatency')
        # it gives unicode but x264enc wants str
        venc.set_property('speed-preset', str(conf.get('x264_speed_preset', 'ultrafast')))

        # It lowers the compression ratio but gives a stable image faster.
        venc.set_property ('key-int-max',30)

        venc.set_property ('bitrate', conf.get('x264_bitrate', 1024))

        for el in [aq, vq, aenc, venc, parser, vmux, vmuxoq, vmuxviq, vsink]:
            self.add(el)

        aq.link(aenc)
        aenc.link(vmux)

        vq.link_filtered(venc, VIDEO_CAPS_SIZE)

        venc.link(parser)
        parser.link(vmuxviq)
        vmuxviq.link(vmux)
        vmux.link(vmuxoq)
        vmuxoq.link(vsink)


        agpad = Gst.GhostPad.new('audiosink', aq.get_static_pad('sink'))
        vgpad = Gst.GhostPad.new('videosink', vq.get_static_pad('sink'))

        self.add_pad(vgpad)
        self.add_pad(agpad)


class StreamWriter(Gst.Bin):
    def __init__(self, name=None, location='/dev/null', append=False):
        Gst.Bin.__init__(self)
        if name:
            self.set_property('name', name)
        self._saving = True

        valve = Gst.ElementFactory.make('valve', None)
        q = Gst.ElementFactory.make('queue2', None)
        fsink = Gst.ElementFactory.make('filesink', None)

        for el in [valve, q, fsink]:
            self.add(el)

        valve.link(q)
        q.link(fsink)

        fsink.set_property('append', append)
        fsink.set_property('location', location)
        valve.set_property('drop', False)

        self.valve = valve
        self.q = q
        self.fsink = fsink

        sinkpad = Gst.GhostPad.new('sink', self.valve.get_static_pad('sink'))
        self.add_pad(sinkpad)

    def stop(self, done=None):
        self._saving = False

        self.valve.set_property('drop', True)
        self.q.set_state(Gst.State.NULL)
        self.fsink.set_state(Gst.State.NULL)

    def start(self, location=None):
        if self._saving:
            self.stop()

        self._saving = True

        if location is not None:
            self.fsink.set_property('location', location)

        self.valve.set_property('drop', False)
        self.q.set_state(Gst.State.PLAYING)
        self.fsink.set_state(Gst.State.PLAYING)

