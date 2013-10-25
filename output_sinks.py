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
from archiving import BaseArchivable, MuxedFileWriter
import config

class BaseOutput(BaseArchivable):
    config_section = None
    _elem_type = 'sink'
    def __init__(self):
        BaseArchivable.__init__(self)

        if self.config_section is not None:
            conf = config.get(self.config_section, {})
            self.conf = conf

        self.stream_writer = None
        self.preview_sink = None

        venc = self._build_video_encoder()
        vpar = self._build_video_parser()
        aenc = self._build_audio_encoder()
        apar = self._build_audio_parser()
        vmux = self._build_muxer()
        sink = self._build_sink()

        els = [venc, aenc, vmux, sink]

        if not all(els):
            return

        els.append(vpar)
        els.append(apar)
        for el in els:
            if el: self.add(el)

        aq = Gst.ElementFactory.make('queue2', 'audio q')
        vq = Gst.ElementFactory.make('queue2', 'video q')

        vmuxoq = Gst.ElementFactory.make('queue2', 'video mux out q')
        vmuxviq = Gst.ElementFactory.make('queue2', 'video mux video in q')
        vmuxaiq = Gst.ElementFactory.make('queue2', 'video mux audio in q')

        aenct = Gst.ElementFactory.make('tee', 'audio enc t')
        venct = Gst.ElementFactory.make('tee', 'video enc t')
        self.aenct = aenct
        self.venct = venct

        for el in [aq, vq, aenct, venct, vmuxoq, vmuxviq, vmuxaiq]:
            self.add(el)

        aq.link(aenc)
        if apar:
            aenc.link(apar)
            caps = Gst.Caps.from_string('audio/mpeg,mpegversion=4,framed=true')
            apar.link_filtered(aenct, caps)
        else:
            aenc.link(aenct)
        aenct.link(vmuxaiq)
        vmuxaiq.link(vmux)

        vq.link_filtered(venc, VIDEO_CAPS_SIZE)

        if vpar:
            venc.link(vpar)
            vpar.link(venct)
        else:
            venc.link(venct)

        venct.link(vmuxviq)
        vmuxviq.link(vmux)
        vmux.link(vmuxoq)
        vmuxoq.link(sink)

        self.add_stream_writer_source(venct)
        self.add_stream_writer_source(aenct)

        agpad = Gst.GhostPad.new('audiosink', aq.get_static_pad('sink'))
        vgpad = Gst.GhostPad.new('videosink', vq.get_static_pad('sink'))

        self.add_pad(vgpad)
        self.add_pad(agpad)

    def initialize(self):
        pass

    def _build_video_encoder(self, *args):
        return None

    def _build_video_parser(self, *args):
        return None

    def _build_audio_encoder(self, *args):
        return None

    def _build_audio_parser(self, *args):
        return None

    def _build_muxer(self, *args):
        return None

    def _build_sink(self, *args):
        return None


class AutoOutput(BaseOutput):
    def __init__(self, name=None):
        BaseOutput.__init__(self)
        if name:
            self.set_property('name', name)

        self.aq = Gst.ElementFactory.make('queue2', 'audio q')
        self.ai = Gst.ElementFactory.make('identity', 'audio i')
        self.vq = Gst.ElementFactory.make('queue2', 'video q')

        self.asink = Gst.ElementFactory.make('autoaudiosink', 'audio sink')
        self.asink = Gst.ElementFactory.make('alsasink', 'audio sink')
        self.vsink = Gst.ElementFactory.make('xvimagesink', 'video sink')
        self.preview_sink = self.vsink

        self.ai.set_property('sync', True)
        self.asink.set_property('sync', False)

        for el in [self.aq, self.ai, self.vq, self.asink, self.vsink]:
            self.add(el)

        self.aq.link(self.ai)
        self.ai.link(self.asink)

        self.vq.link_filtered(self.vsink, VIDEO_CAPS_SIZE)

        agpad = Gst.GhostPad.new('audiosink', self.aq.get_static_pad('sink'))
        vgpad = Gst.GhostPad.new('videosink', self.vq.get_static_pad('sink'))

        self.add_pad(vgpad)
        self.add_pad(agpad)

    def initialize(self):
        self.preview_sink.set_property('sync', XV_SYNC)


class BaseH264Output(BaseOutput):
    def _build_video_parser(self, *args):
        parser = Gst.ElementFactory.make ('h264parse', None)
        parser.set_property ('config-interval',2)
        return parser

    def _build_audio_encoder(self, *args):
        conf = self.conf
        aenc = Gst.ElementFactory.make('voaacenc', None) or Gst.ElementFactory.make('faac', None)
        aenc.set_property('bitrate', conf.setdefault('audio_bitrate', 192000))
        return aenc

    def _build_audio_parser(self, *args):
        # XXX FIXME: recent version of Gstremer now require a parser
        # but on older it fails, so?
        parser = Gst.ElementFactory.make ('aacparse', None)
        return parser

    def _build_sink(self, *args):
        conf = self.conf
        vsink = Gst.ElementFactory.make ('tcpserversink', None)
        vsink.set_property('sync-method', 4) # burst-keyframe - Serve burst-value data starting on a keyframe
        # remember to change them in the streaming server if you
        # stray away from the defaults
        vsink.set_property('host', conf.setdefault('host', '127.0.0.1'))
        vsink.set_property('port', conf.setdefault('port', 9078))

        return vsink

class MP4Output(BaseH264Output):
    _mux_pad_names = ['video_%u', 'audio_%u']
    filename_suffix = '.mp4'
    config_section = 'MP4Output'
    def __init__(self, name=None):
        BaseH264Output.__init__(self)
        if name:
            self.set_property('name', name)

    def _build_video_encoder(self, *args):
        conf = self.conf
        venc = Gst.ElementFactory.make ('x264enc', None)
        venc.set_property('byte-stream', True)
        venc.set_property('tune', 'zerolatency')
        # it gives unicode but x264enc wants str
        venc.set_property('speed-preset', str(conf.setdefault('x264_speed_preset', 'ultrafast')))
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

        venc.set_property ('bitrate', conf.setdefault('x264_bitrate', 1024))
        return venc

    def _build_muxer(self):
        conf = self.conf
        vmux = Gst.ElementFactory.make ('mp4mux', None)
        vmux.set_property('streamable', True)
        vmux.set_property('fragment-duration', 1000)

        # the default (reorder) gives a nicer and faster a/v sync
        # but x264 produces frames with  DTS timestamp and that doesn't need
        # to be always increasing. So mp4mux is not happy, see gstqtmux.c around
        # line 2800.
        vmux.set_property('dts-method', 2) # ascending

        return vmux


class FLVOutput(BaseH264Output):
    _mux_pad_names = ['audio', 'video']
    filename_suffix = '.flv'
    config_section = 'FLVOutput'
    def __init__(self, name=None):
        BaseH264Output.__init__(self)
        if name:
            self.set_property('name', name)

    def _build_video_encoder(self, *args):
        conf = self.conf
        venc = Gst.ElementFactory.make ('x264enc', None)
        venc.set_property('byte-stream', True)
        venc.set_property('tune', 'zerolatency')
        # it gives unicode but x264enc wants str
        venc.set_property('speed-preset', str(conf.setdefault('x264_speed_preset', 'ultrafast')))

        # It lowers the compression ratio but gives a stable image faster.
        venc.set_property ('key-int-max',30)
        venc.set_property ('bitrate', conf.setdefault('x264_bitrate', 1024))

        return venc

    def _build_muxer(self):
        vmux = Gst.ElementFactory.make ('flvmux', None)
        vmux.set_property('streamable', True)
        return vmux

class MKVOutput(BaseH264Output):
    _mux_pad_names = ['audio_%u', 'video_%u']
    filename_suffix = '.mkv'
    config_section = 'MKVOutput'
    def __init__(self, name=None):
        BaseH264Output.__init__(self)
        if name:
            self.set_property('name', name)

    def _build_video_encoder(self, *args):
        conf = self.conf
        venc = Gst.ElementFactory.make ('x264enc', None)
        venc.set_property('byte-stream', True)
        venc.set_property('tune', 'zerolatency')
        # it gives unicode but x264enc wants str
        venc.set_property('speed-preset', str(conf.setdefault('x264_speed_preset', 'ultrafast')))

        # It lowers the compression ratio but gives a stable image faster.
        venc.set_property ('key-int-max',30)
        venc.set_property ('bitrate', conf.setdefault('x264_bitrate', 1024))

        return venc

    def _build_muxer(self):
        vmux = Gst.ElementFactory.make ('matroskamux', None)
        vmux.set_property('streamable', True)
        return vmux



class InterSink(BaseArchivable):
    config_section = None
    _elem_type = 'sink'
    def __init__(self, source=None, channel='channel-1'):
        BaseArchivable.__init__(self)
        self.channel = channel
        self.source = None

        desc = 'intervideosink name=interv channel=%s interaudiosink name=intera channel=%s' % (channel, channel)

        p = Gst.parse_launch(desc)
        self.pipeline = p

        self.add_pad(Gst.GhostPad.new('audiosink', p.get_by_name('intera').get_static_pad('sink')))
        self.add_pad(Gst.GhostPad.new('videosink', p.get_by_name('interv').get_static_pad('sink')))

##        bus = self.bus = p.get_bus()
##        bus.add_signal_watch()
##        bus.connect("message::state-changed", self.bus_state_changed_cb)
##        bus.connect("message::element", self.bus_element_cb)
##        bus.connect("message", self.bus_message_cb)
        self._last_state = [None, None, None]
        p.add(self)
        p.set_state(Gst.State.PLAYING)

        if source:
            self.set_source(source)

    def set_source(self, source):
        self.source = source
        self.pipeline.add(source)
        logging.debug('InterSink %s link audio: %s', self.channel, source.link_pads('audiosrc', self, 'audiosink'))
        logging.debug('InterSink %s link video: %s', self.channel, source.link_pads('videosrc', self, 'videosink'))
        source.sync_state_with_parent()
        self.pipeline.set_state(Gst.State.PLAYING)

class InterSHMSink(BaseArchivable):
    config_section = None
    _elem_type = 'sink'
    def __init__(self, source=None, channel='channel-1'):
        BaseArchivable.__init__(self)
        channel = os.path.join('/dev/shm/', channel)
        self.channel = channel
        self.source = None

        desc = 'shmsink name=vsink shmsink name=asink'

        p = Gst.parse_launch(desc)
        self.pipeline = p

        vsink = p.get_by_name('vsink')
        vsink.set_property('shm-size', SHM_SIZE)
        sockpath = self.channel+'-video'
        try:
            os.remove(sockpath)
        except OSError:
            pass
        vsink.set_property('socket-path', sockpath)
        vsink.set_property('wait-for-connection', False)

        asink = p.get_by_name('asink')
        asink.set_property('shm-size', SHM_SIZE)
        sockpath = self.channel+'-audio'
        try:
            os.remove(sockpath)
        except OSError:
            pass
        asink.set_property('socket-path', sockpath)
        asink.set_property('wait-for-connection', False)

        self.add_pad(Gst.GhostPad.new('audiosink', p.get_by_name('asink').get_static_pad('sink')))
        self.add_pad(Gst.GhostPad.new('videosink', p.get_by_name('vsink').get_static_pad('sink')))

##        bus = self.bus = p.get_bus()
##        bus.add_signal_watch()
##        bus.connect("message::state-changed", self.bus_state_changed_cb)
##        bus.connect("message::element", self.bus_element_cb)
##        bus.connect("message", self.bus_message_cb)
        self._last_state = [None, None, None]
        p.add(self)
        logging.debug('SHM set to PLAY: %s', p.set_state(Gst.State.PLAYING))

        if source:
            self.set_source(source)

    def set_source(self, source):
        self.source = source
        self.pipeline.add(source)
        logging.debug('InterSink %s link audio: %s', self.channel, source.link_pads('audiosrc', self, 'audiosink'))
        logging.debug('InterSink %s link video: %s', self.channel, source.link_pads('videosrc', self, 'videosink'))
        source.sync_state_with_parent()
        logging.debug('SHM set to PLAY from set_source(): %s', self.pipeline.set_state(Gst.State.PLAYING))

