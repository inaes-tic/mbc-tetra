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
    __gsignals__ = {
       "ready-to-record": (GObject.SIGNAL_RUN_FIRST, None, []),
       "record-stopped": (GObject.SIGNAL_RUN_FIRST, None, []),
    }
    def __init__(self):
        Gst.Bin.__init__(self)
        self.filename_suffix = ''
        self.stream_writer = None
        self._stream_writer_sources = []

    def __contains__ (self, item):
        return item in self.children

    def initialize(self):
        pass

    def get_record_filename(self, folder=None, name_template=None):
        conf = config.get('FileArchiving', {})
        if folder is None:
            folder = conf.setdefault('folder', None)
        if name_template is None:
            name_template = conf.setdefault('name_template', 'captura_tetra')

        if folder is None:
            return False

        if not os.path.isdir(folder):
            os.makedirs(folder)

        now = time.localtime()
        now = time.strftime("%Y-%m-%d-%H:%M:%S", now)

        name = '%s-%s%s' % (name_template, now, self.filename_suffix)
        fullname = os.path.join(folder, name)

        return fullname

    def _build_muxer(self, *args):
        return None

    def stop_file_recording(self):
        sw = self.stream_writer
        if sw:
            sw.stop()
        else:
            self.emit('record-stopped')

    def start_file_recording(self, location=None):
        def sw_stopped_cb(ssw):
            self.remove(ssw)
            self.stream_writer = None
            self.emit('record-stopped')

        def add_sw(location='/dev/null'):
            mux = self._build_muxer()
            if not mux:
                return False
            sw = MuxedFileWriter(mux, location=location)
            sw.connect('stopped', sw_stopped_cb)
            self.stream_writer = sw
            self.add(sw)

            for src in self._stream_writer_sources:
                src.link(sw)
            sw.set_state(self.get_state(0)[1])
            return True

        if self.stream_writer is None:
            location = self.get_record_filename()
            if location and add_sw(location):
                logging.debug('Start archiving to: %s', location)
                self.emit('ready-to-record')
            else:
                return False
        else:
            self.stream_writer.stop()

        return True

class AutoOutput(BaseOutput):
    def __init__(self, name=None):
        BaseOutput.__init__(self)
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
        self.filename_suffix = '.mp4'

        conf = config.get('MP4Output', {})
        self.conf = conf

        aq = Gst.ElementFactory.make('queue2', 'audio q')
        vq = Gst.ElementFactory.make('queue2', 'video q')
        vmuxoq = Gst.ElementFactory.make('queue2', 'video mux out q')
        vmuxviq = Gst.ElementFactory.make('queue2', 'video mux video in q')
        vmuxaiq = Gst.ElementFactory.make('queue2', 'video mux audio in q')
        self.preview_sink = None

        streamvq = Gst.ElementFactory.make('queue2', 'video archive q')
        streamaq = Gst.ElementFactory.make('queue2', 'audio archive q')
##        for q in [streamvq, streamaq]:
##            q.set_property('max-size-time', 10*Gst.SECOND)

        aenc = Gst.ElementFactory.make('avenc_aac', None)
        aenc.set_property('bitrate', conf.setdefault('audio_bitrate', 192000))

        vsink = Gst.ElementFactory.make ('tcpserversink', None)
        # remember to change them in the streaming server if you
        # stray away from the defaults
        vsink.set_property('host', conf.setdefault('host', '127.0.0.1'))
        vsink.set_property('port', conf.setdefault('port', 9078))

        vmux = self._build_muxer()

        parser = Gst.ElementFactory.make ('h264parse', None)
        parser.set_property ('config-interval',2)

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

        aenct = Gst.ElementFactory.make('tee', 'audio enc t')
        venct = Gst.ElementFactory.make('tee', 'video enc t')
        self.aenct = aenct
        self.venct = venct

        for el in [aq, vq, aenc, venc, aenct, venct, parser, vmux, vmuxoq, vmuxviq, vmuxaiq, streamvq, streamaq, vsink]:
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

        venct.link(streamvq)
        aenct.link(streamaq)

        self._stream_writer_sources.append(streamvq)
        self._stream_writer_sources.append(streamaq)

        agpad = Gst.GhostPad.new('audiosink', aq.get_static_pad('sink'))
        vgpad = Gst.GhostPad.new('videosink', vq.get_static_pad('sink'))

        self.add_pad(vgpad)
        self.add_pad(agpad)


    def _build_muxer(self):
        vmux = Gst.ElementFactory.make ('mp4mux', None)
        vmux.set_property('streamable', True)
        vmux.set_property('fragment-duration', 1000)

        # the default (reorder) gives a nicer and faster a/v sync
        # but x264 produces frames with  DTS timestamp and that doesn't need
        # to be always increasing. So mp4mux is not happy, see gstqtmux.c around
        # line 2800.
        vmux.set_property('dts-method', 2) # ascending

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
        vsink.set_property('host', conf.setdefault('host', '127.0.0.1'))
        vsink.set_property('port', conf.setdefault('port', 9078))

        vmux = Gst.ElementFactory.make ('flvmux', None)
        vmux.set_property('streamable', True)

        parser = Gst.ElementFactory.make ('h264parse', None)
        parser.set_property ('config-interval',2)

        venc = Gst.ElementFactory.make ('x264enc', None)
        venc.set_property('byte-stream', True)
        venc.set_property('tune', 'zerolatency')
        # it gives unicode but x264enc wants str
        venc.set_property('speed-preset', str(conf.setdefault('x264_speed_preset', 'ultrafast')))

        # It lowers the compression ratio but gives a stable image faster.
        venc.set_property ('key-int-max',30)

        venc.set_property ('bitrate', conf.setdefault('x264_bitrate', 1024))

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


class MuxedFileWriter(Gst.Bin):
    __gsignals__ = {
       "stopped": (GObject.SIGNAL_RUN_FIRST, None, []),
    }
    def __init__(self, mux, name=None, location='/dev/null', append=True, pad_names=None):
        Gst.Bin.__init__(self)
        if name:
            self.set_property('name', name)


        q = Gst.ElementFactory.make('queue2', None)

        fsink = Gst.ElementFactory.make('filesink', None)
        fsink.set_property('append', append)
        fsink.set_property('location', location)

        self.mux = mux
        self.fsink = fsink

        for el in [mux, q, fsink]:
            self.add(el)

        mux.link(q)
        q.link(fsink)

        # XXX FIXME: need to make this work in a dynamic fashion
        if pad_names is None:
            pad_names = ['video_%u', 'audio_%u']
        for name in pad_names:
            pad = mux.get_request_pad(name)
            gpad = Gst.GhostPad.new(name, pad)
            self.add_pad(gpad)

    def __set_to_null_and_stop(self):
        self.set_state(Gst.State.NULL)
        for pad in self.pads:
            peer = pad.get_peer()
            if peer is not None:
                logging.debug('UNLINK PAD %s', pad)
                # we are a sink, so the roles of pad and peer are reversed
                # with respect to the same block in input_sources.py
                peer.unlink(pad)
                parent = peer.get_parent()

                presence = None
                tmpl = peer.get_pad_template()
                if tmpl:
                    presence = tmpl.presence
                if parent and (presence == Gst.PadPresence.REQUEST):
                    logging.debug('BEFORE PAD PARENT RELEASE PAD')
                    parent.release_request_pad(peer)
                    logging.debug('PAD PARENT RELEASE PAD OK')
        self.emit('stopped')

    def stop(self, *args):
        probes = []
        pads = self.pads

        def pad_block_cb(pad, probe_info, *data):
            ok = True
            for pad in pads:
                if pad.is_blocked() == False:
                    ok = False
            if ok:
                GLib.timeout_add(0, self.__set_to_null_and_stop)
            return Gst.PadProbeReturn.REMOVE

        for pad in pads:
            probes.append( [pad, pad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM | Gst.PadProbeType.BLOCK_UPSTREAM, pad_block_cb, None)] )

        if self.get_state(0)[1] != Gst.State.PLAYING:
            GLib.timeout_add(0, self.__set_to_null_and_stop)


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

