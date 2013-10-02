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

class BaseArchivable(Gst.Bin):
    __gsignals__ = {
       "ready-to-record": (GObject.SIGNAL_RUN_FIRST, None, []),
       "record-stopped": (GObject.SIGNAL_RUN_FIRST, None, []),
    }
    filename_suffix = ''
    _mux_pad_names = None
    _filename_template = None

    def __init__(self):
        Gst.Bin.__init__(self)
        self._stream_writer_sources = []

    def add_stream_writer_source(self, src):
        self._stream_writer_sources.append(src)

    def get_record_filename(self, folder=None, name_template=None):
        conf = config.get('FileArchiving', {})
        if folder is None:
            folder = conf.setdefault('folder', None)
        if name_template is None and not self._filename_template:
            name_template = conf.setdefault('name_template', 'captura_tetra')
        else:
            name_template = self._filename_template

        if folder is None:
            return False

        if not os.path.isdir(folder):
            os.makedirs(folder)

        now = time.localtime()
        now = time.strftime("%Y-%m-%d-%H:%M:%S", now)

        name = '%s-%s%s' % (name_template, now, self.filename_suffix)
        fullname = os.path.join(folder, name)

        return fullname

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
            sw = MuxedFileWriter(mux, location=location, pad_names=self._mux_pad_names)
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
            gpad = Gst.GhostPad.new(None, pad)
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
### In our case peer is a queue's src, so this path should not be taken.
### Yet uncommenting it releases demons.
###                parent = peer.get_parent()
###
###                presence = None
###                tmpl = peer.get_pad_template()
###                if tmpl:
###                    presence = tmpl.presence
###                if parent and (presence == Gst.PadPresence.REQUEST):
###                    logging.debug('BEFORE PAD PARENT RELEASE PAD')
###                    parent.release_request_pad(peer)
###                    logging.debug('PAD PARENT RELEASE PAD OK')
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

