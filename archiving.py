#!/usr/bin/env python

import logging

import threading
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
from gstcommon import BaseBin
import config

class BaseArchivable(BaseBin):
    __gsignals__ = {
       "ready-to-record": (GObject.SIGNAL_RUN_FIRST, None, []),
       "record-stopped": (GObject.SIGNAL_RUN_FIRST, None, []),
    }
    filename_suffix = ''
    _mux_pad_names = None
    _filename_template = None
    _elem_type = 'sink'

    def __init__(self):
        BaseBin.__init__(self)
        self._stream_writer_sources = []
        self.stream_writer = None

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
            sw.connect('removed', sw_stopped_cb)
            self.stream_writer = sw
            self.add(sw)

            for src in self._stream_writer_sources:
                logging.debug('STREAM WRITER LINK ok?: %s', src.link(sw))
            sw.sync_state_with_parent()
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


class MuxedFileWriter(BaseBin):
    __gsignals__ = {
       "stopped": (GObject.SIGNAL_RUN_FIRST, None, []),
    }
    _elem_type = 'sink'

    def __init__(self, mux, name=None, location='/dev/null', append=True, pad_names=None):
        Gst.Bin.__init__(self)
        if name:
            self.set_property('name', name)

        self._on_unlink = False
        self._on_unlink_lck = threading.Lock()
        self._probes = {}

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
            q = Gst.ElementFactory.make('queue2', None)
            self.add(q)
            q.link_pads('src', mux, name)
            pad = q.get_static_pad('sink')
            gpad = Gst.GhostPad.new(None, pad)
            self.add_pad(gpad)

    def stop(self, *args):
        self.disconnect_element()

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

