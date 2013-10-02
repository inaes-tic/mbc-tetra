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

GObject.threads_init()

from common import *
from archiving import BaseArchivable
AUDIO_PROPS = { 'do-timestamp': True }
VIDEO_PROPS = {}
VIDEO_PROPS = { 'do-timestamp': True }

class GeneralInputError(Exception):
    pass

class BaseInput(BaseArchivable):
    __gsignals__ = {
       "removed": (GObject.SIGNAL_RUN_FIRST, None, []),
    }
    def __init__(self):
        Gst.Bin.__init__(self)
        BaseArchivable.__init__(self)
        self.volume = None
        self.xvsink = None
        self.level = None
        self.vcaps = None
        self._on_error = False
        self._on_error_lck = threading.Lock()
        self._probes = {}

    def set_volume(self, volume):
        if self.volume is None:
            return
        if volume > 1.5:
            volume = 1.5
        elif volume < 0:
            volume = 0
        self.volume.set_property('volume', volume)

    def set_geometry(self, width=None, height=None):
        if not self.vcaps:
            return

        tmpl = 'video/x-raw, framerate=%s ' % VIDEO_RATE
        if width:
            tmpl += ',width=%i' % width
        if height:
            tmpl += ',height=%i' % height

        caps = Gst.Caps.from_string(tmpl)
        if caps:
            self.vcaps.set_property('caps', caps)

    def set_mute(self, mute):
        if self.volume is None:
            return
        self.volume.set_property('mute', mute)

    def initialize(self):
        pass

    def __contains__ (self, item):
        return item in self.children

    def __unlink_and_set_to_null (self):
        parent = self.get_parent()
        logging.debug('SET EL %s TO NULL %s', self, self.set_state(Gst.State.NULL))

        for pad in self.pads:
            peer = pad.get_peer()
            if peer is not None:
                logging.debug('UNLINK PAD %s', pad)
                pad.unlink(peer)
                parent = peer.get_parent()

                presence = None
                tmpl = peer.get_pad_template()
                if tmpl:
                    presence = tmpl.presence
                if parent and (presence == Gst.PadPresence.REQUEST):
                    logging.debug('BEFORE PAD PARENT RELEASE PAD')
                    parent.release_request_pad(peer)
                    logging.debug('PAD PARENT RELEASE PAD OK')

        logging.debug('SET EL TO NULL OK? %s', self)

        self.emit('removed')

        return False

    def pad_block_cb(self, pad, probe_info, data=None):
        ok = True
        logging.debug('PAD BLOCK CB')
        for pad in self.pads:
            logging.debug('PAD BLOCK CB, PAD IS BLOCKED? %s %s', pad.is_blocked(), pad)
            if pad.is_blocked() == False:
                ok = False
        if ok:
            logging.debug('PAD BLOCK ADD IDLE')
            for p, probe in self._probes.items():
                p.remove_probe(probe)
            GLib.timeout_add(500, self.__unlink_and_set_to_null)
            return Gst.PadProbeReturn.REMOVE

        return Gst.PadProbeReturn.OK

    def do_handle_message(self, message):
        if not message:
            return

        if message.type == Gst.MessageType.ERROR:
            if self._on_error_lck.acquire(True):
                if not self._on_error:
                    logging.error('ERROR en src :%s %s', message, message.parse_error())
                    self._on_error = True
                    Gst.Bin.do_handle_message(self, message)
                self._on_error_lck.release()
            return

        Gst.Bin.do_handle_message(self, message)

    def disconnect_source(self):
        # in order to properly remove ourselves from the pipeline we need to block
        # our pads, when all of them are blocked we can safely unlink *from the main thread*
        # (that's what the timeout_add() is for).
        # However, if no buffers are currently flowing (or won't be) the probe never succedes.
        # Common wisdom suggest to use a custom event but, if we are in a null state
        # (like, we tried to open a non-existing device upon starting), this will also fail.
        # So in that case we just unlink and hope for the best.
        state = self.get_state(0)
        logging.debug('DISCONNECT SOURCE CURRENT STATE %s', state)
        if state[1] == Gst.State.NULL:
            GLib.timeout_add(10, self.__unlink_and_set_to_null)
            logging.debug('PAD BLOCK ADD TIMEOUT disconnect_source STATE IS NULL')
            return False

        ok = True
        for pad in self.pads:
            if pad.is_blocked() == False:
                ok = False
                if pad not in self._probes:
                    self._probes[pad] = pad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM | Gst.PadProbeType.BLOCK_UPSTREAM, self.pad_block_cb, None)
                    logging.debug('DISCONNECT SOURCE ADD PAD PROBE FOR %s PAD IS BLOCKED? %s PAD IS LINKED? %s', pad, pad.is_blocked(), pad.is_linked())
        if ok:
            GLib.timeout_add(10, self.__unlink_and_set_to_null)
            logging.debug('PAD BLOCK ADD TIMEOUT disconnect_source')
        return False

class C920Input(BaseInput):
    _mux_pad_names = ['video_%u', 'audio_%u']
    filename_suffix = '.mkv'
    def __init__(self, video_props, audio_props, name=None, serial='', *args, **kwargs):
        BaseInput.__init__(self)
        if name:
            self.set_property('name', name)

        self._filename_template = serial
        self.asink = None
        self.vsink = None

        self.__add_video_source(video_props)
        self.__add_audio_source(audio_props)

        if not (self.asink and self.vsink):
            raise GeneralInputError('Cannot create audio or video source')

        agpad = Gst.GhostPad.new('audiosrc', self.asink.get_static_pad('src'))
        vgpad = Gst.GhostPad.new('videosrc', self.vsink.get_static_pad('src'))

        self.vgpad = vgpad
        self.agpad = agpad

        self.add_pad(agpad)
        self.add_pad(vgpad)


    def initialize(self):
        self.set_uvc_controls()
        self.xvsink.set_property('sync', XV_SYNC)

    def set_uvc_controls (self):
        controls = {
            'Power Line Frequency': 1,
            # we want this to have a constant framerate.
            'Exposure, Auto Priority': 0
        }

        cmd = "uvcdynctrl -s '%s' '%s' --device=%s"
        for ctrl, value in controls.items():
            dev = self.vsrc.get_property('device')
            logging.info('%s setting %s to %s' % (dev, ctrl, value))
            os.system(cmd % (ctrl, str(value), dev))

    def _build_muxer(self, *args):
        vmux = Gst.ElementFactory.make('matroskamux', None)
        vmux.set_property('streamable', True)
        return vmux

    def __add_video_source (self, props):
# XXX FIXME: cambiar el jpeg por raw mas luego.
        props.update(VIDEO_PROPS)
        name = props.get('name', 'v4l2src')
        src = Gst.ElementFactory.make (name, None)
        q0 = Gst.ElementFactory.make ('queue2', None)
        tee = Gst.ElementFactory.make ('tee', None)
        parse = Gst.ElementFactory.make ('jpegparse', None)
        dec = Gst.ElementFactory.make ('jpegdec', None)
        q1 = Gst.ElementFactory.make ('queue2', None)
        q2 = Gst.ElementFactory.make ('queue2', None)
        streamvq = Gst.ElementFactory.make('queue', 'video archive q')
        streamvq.set_property('silent', True)
        streamvt = Gst.ElementFactory.make ('tee', None)
        vconv = Gst.ElementFactory.make ('videoconvert', None)
        vscale = Gst.ElementFactory.make ('videoscale', None)
        vcaps = Gst.ElementFactory.make ('capsfilter', None)
        sink = Gst.ElementFactory.make ('xvimagesink', None)
        sink.set_property('sync', XV_SYNC)

        self.xvsink = sink
        self.vsrc = src
        self.vcaps = vcaps

        for el in (src, sink, q0, q1, q2, streamvq, streamvt, tee, parse, dec, vconv, vscale, vcaps):
            self.add(el)

        if props:
            for prop,val in props.items():
                src.set_property(prop, val)

# XXX:
        #q0.set_property ('max-size-time', int(1*Gst.SECOND))
        src.link(q0)
        q0.link_filtered(streamvt, VIDEO_CAPS)
        streamvt.link_filtered(parse, VIDEO_CAPS)
        streamvt.link(streamvq)
        parse.link(dec)
        dec.link(tee)
        tee.link(q1)
        tee.link(q2)
        q2.link(sink)
        q1.link(vconv)
        vconv.link(vscale)
        vscale.link(vcaps)
        self.vsink = vcaps

        self.add_stream_writer_source(streamvq)

    def __add_audio_source (self, props):
        props.update(AUDIO_PROPS)
        C920_AUDIO_CAPS = Gst.Caps.from_string ('audio/x-raw,format=S16LE,rate=32000,channels=2')
        name = props.get('name', 'alsasrc')
        src = Gst.ElementFactory.make (name, None)
        q0 = Gst.ElementFactory.make ('queue2', None)
        q1 = Gst.ElementFactory.make ('queue2', None)
        q2 = Gst.ElementFactory.make ('queue2', None)
        q3 = Gst.ElementFactory.make ('queue2', None)
        streamaq = Gst.ElementFactory.make('queue', 'audio archive q')
        streamaq.set_property('silent', True)
        self.asink = q2
        tee = Gst.ElementFactory.make ('tee', None)
        volume = Gst.ElementFactory.make ('volume', None)
        self.volume = volume
#
        fasink = Gst.ElementFactory.make ('fakesink', None)
        fasink.set_property ('sync', False)
#
        aconv = Gst.ElementFactory.make ('audioconvert', None)
        aconv2 = Gst.ElementFactory.make ('audioconvert', None)
        ares = Gst.ElementFactory.make ('audioresample', None)

        flt = Gst.ElementFactory.make ('audiochebband', None)
        flt.set_property ('lower-frequency', 400)
        flt.set_property ('upper-frequency', 3500)
        # 10 samples per second
        level = Gst.ElementFactory.make ('level', None)
        level.set_property ("message", True)
        self.level = level

        for el in (src, q0, q1, q2, q3, streamaq, tee, volume, fasink, aconv, aconv2, ares, flt, level):
            self.add(el)

        if props:
            for prop,val in props.items():
                src.set_property (prop, val)

        src.link_filtered (q0, C920_AUDIO_CAPS)
        q0.link (volume)
        volume.link (tee)
        tee.link (q1)
        tee.link (q3)
        tee.link (streamaq)
        q3.link (aconv2)
        aconv2.link(ares)
        ares.link(q2)
        q1.link (aconv)
        aconv.link (flt)
        flt.link (level)
        level.link(fasink)

        self.add_stream_writer_source(streamaq)

GObject.type_register(C920Input)


def C920Probe(device, context):
    model = device.get('ID_MODEL', None)
    if model != u'HD_Pro_Webcam_C920':
        return False

    vdev = device.get('DEVNAME', None)
    adev = None

    serial = device['ID_SERIAL_SHORT']
    sounds = context.list_devices().match_property('ID_SERIAL_SHORT', serial).match_subsystem('sound')
    for snd in sounds:
        if 'id' in snd.attributes:
            adev = snd.attributes['id']
            break
    if adev and vdev:
        vprops = {'device': vdev}
        aprops = {'device': 'hw:CARD=%s' % adev}
        return (C920Input, {'video_props':vprops, 'audio_props':aprops, 'serial':device['ID_SERIAL']})

    return False


class TestInput(BaseInput):
    def __init__(self, name=None):
        BaseInput.__init__(self)
        if name:
            self.set_property('name', name)

        self.asink = None
        self.vsink = None

        props = {
            'is_live': True,
            'do-timestamp': True,
        }

        aprops = {
            'freq': 0,
            'volume': 0,
        }
        aprops.update(props)

        self.__add_video_source(props)
        self.__add_audio_source(aprops)

        if not (self.asink and self.vsink):
            raise GeneralInputError('Cannot create audio or video source')

        agpad = Gst.GhostPad.new('audiosrc', self.asink.get_static_pad('src'))
        vgpad = Gst.GhostPad.new('videosrc', self.vsink.get_static_pad('src'))

        self.add_pad(agpad)
        self.add_pad(vgpad)

    def __add_video_source(self, props):
        src = Gst.ElementFactory.make ('videotestsrc', None)
        q0 = Gst.ElementFactory.make ('identity', None)
        tee = Gst.ElementFactory.make ('tee', None)
        conv = Gst.ElementFactory.make ('videoconvert', None)
        q1 = Gst.ElementFactory.make ('identity', None)
        q2 = Gst.ElementFactory.make ('queue2', None)
        sink = Gst.ElementFactory.make ('xvimagesink', None)
        sink.set_property('sync', XV_SYNC)

        self.xvsink = sink
        self.vsink = q1
        self.vsrc = src

        for el in (src, sink, q0, q1, q2, tee, conv):
            self.add(el)

        props.update(VIDEO_PROPS)
        if props:
            for prop,val in props.items():
                src.set_property(prop, val)

# XXX:
        #q0.set_property ('max-size-time', int(1*Gst.SECOND))
        src.link_filtered(q0, VIDEO_CAPS_SIZE)
        q0.link_filtered(tee, VIDEO_CAPS_SIZE)
        tee.link(conv)
        conv.link_filtered(q1, VIDEO_CAPS_SIZE)
        tee.link(q2)
        q2.link_filtered(sink, VIDEO_CAPS_SIZE)

    def __add_audio_source(self, props):
        src = Gst.ElementFactory.make ('audiotestsrc', None)
        q0 = Gst.ElementFactory.make ('queue2', None)
        q1 = Gst.ElementFactory.make ('queue2', None)
        q2 = Gst.ElementFactory.make ('queue2', None)
        self.asink = q2
        tee = Gst.ElementFactory.make ('tee', None)
        volume = Gst.ElementFactory.make ('volume', None)
        self.volume = volume
#
        fasink = Gst.ElementFactory.make ('fakesink', None)
        fasink.set_property ('sync', False)
#

        # 10 samples per second
        level = Gst.ElementFactory.make ('level', None)
        level.set_property ("message", True)
        self.level = level

        for el in (src, q0, q1, q2, tee, volume, fasink, level):
            self.add(el)

        if props:
            for prop,val in props.items():
                src.set_property (prop, val)

        caps = AUDIO_CAPS
        src.link_filtered (q0, caps)
        q0.link (volume)
        volume.link (tee)
        tee.link (q1)
        tee.link (q2)
        q1.link (level)
        level.link(fasink)


GObject.type_register(TestInput)


class AlsaInput(BaseInput):
    def __init__(self, audio_props=None, name=None):
        BaseInput.__init__(self)
        if name:
            self.set_property('name', name)

        self.asink = None

        self.__add_audio_source(audio_props)

        if not self.asink:
            raise GeneralInputError('Cannot create audio or video source')

        agpad = Gst.GhostPad.new('audiosrc', self.asink.get_static_pad('src'))

        self.add_pad(agpad)

    def set_device(self, device):
        if device == self.device:
            return

        self.asrc.set_property('device', device)
        state = self.get_state(0)[1]
        self.asrc.set_state(Gst.State.NULL)
        self.asrc.set_state(state)
        #self.asrc.set_state(Gst.State.PLAYING)
        self.device = device

    def __add_audio_source (self, props):
        if props is None:
            props = { 'device':'default' }
        props.update(AUDIO_PROPS)
        self.device = props['device']
        name = props.get('name', 'alsasrc')
        src = Gst.ElementFactory.make (name, None)
        self.asrc = src
        q0 = Gst.ElementFactory.make ('queue2', None)
        q1 = Gst.ElementFactory.make ('queue2', None)
        q2 = Gst.ElementFactory.make ('queue2', None)
        q3 = Gst.ElementFactory.make ('queue2', None)
        self.asink = q2
        tee = Gst.ElementFactory.make ('tee', None)
        volume = Gst.ElementFactory.make ('volume', None)
        self.volume = volume
#
        fasink = Gst.ElementFactory.make ('fakesink', None)
        fasink.set_property ('sync', False)
#
        aconv = Gst.ElementFactory.make ('audioconvert', None)
        aconv2 = Gst.ElementFactory.make ('audioconvert', None)
        ares = Gst.ElementFactory.make ('audioresample', None)

        flt = Gst.ElementFactory.make ('audiochebband', None)
        flt.set_property ('lower-frequency', 400)
        flt.set_property ('upper-frequency', 3500)
        # 10 samples per second
        level = Gst.ElementFactory.make ('level', None)
        level.set_property ("message", True)
        self.level = level

        for el in (src, q0, q1, q2, q3, tee, volume, fasink, aconv, aconv2, ares, flt, level):
            self.add(el)

        if props:
            for prop,val in props.items():
                src.set_property (prop, val)

        src.link (q0)
        q0.link (volume)
        volume.link (tee)
        tee.link (q1)
        tee.link (q3)
        q3.link (aconv2)
        aconv2.link (ares)
        ares.link (q2)
        q1.link (aconv)
        aconv.link (flt)
        flt.link (level)
        level.link(fasink)


GObject.type_register(AlsaInput)


class ImageSource(BaseInput):
    def __init__(self, location=None, x_offset=None, y_offset=None, width=VIDEO_WIDTH, height=VIDEO_HEIGHT, alpha=1, name=None):
        BaseInput.__init__(self)
        if name:
            self.set_property('name', name)

        self.xvsink = None
        self.level = None

        overlay = Gst.ElementFactory.make ('gdkpixbufoverlay', None)
        self.overlay = overlay

        vtestsrc = Gst.ElementFactory.make ('videotestsrc', None)
        props = {
            'foreground-color': 0xFFFFFFFF,
            'background-color': 0,
            'pattern': 'solid-color',
            'do-timestamp': True,
            'is-live': True,
        }
        for prop, value in props.items():
            vtestsrc.set_property(prop, value)

        atestsrc = Gst.ElementFactory.make ('audiotestsrc', None)
        props = {
            'wave': 'silence',
            'volume': 0,
            'do-timestamp': True,
            'is-live': True,
        }
        for prop, value in props.items():
            atestsrc.set_property(prop, value)

        q1 = Gst.ElementFactory.make ('queue', None)
        q2 = Gst.ElementFactory.make ('queue', None)

        props = {
            'max-size-buffers': 100,
            'leaky': 'upstream',
            'silent': True,
        }
        for prop, value in props.items():
            q1.set_property(prop, value)
            q2.set_property(prop, value)

        for el in [overlay, vtestsrc, atestsrc, q1, q2]:
            self.add(el)

        atestsrc.link(q1)
        self.asink = q1
        agpad = Gst.GhostPad.new('audiosrc', self.asink.get_static_pad('src'))
        self.agpad = agpad

        vtestsrc.link_filtered(overlay, VIDEO_CAPS_SIZE)

        overlay.link(q2)
        self.vsink = q2
        vgpad = Gst.GhostPad.new('videosrc', self.vsink.get_static_pad('src'))
        self.vgpad = vgpad

        self.add_pad(vgpad)
        self.add_pad(agpad)

        self.overlay.set_property('location', location)

        if width:
                self.overlay.set_property('overlay-width', width)

        if height:
            self.overlay.set_property('overlay-height', height)

        self.overlay.set_property('alpha', alpha)

        if x_offset is not None:
            if x_offset > 1:
                self.overlay.set_property('offset-x', x_offset)
            else:
                self.overlay.set_property('relative-x', x_offset)

        if y_offset is not None:
            if y_offset > 1:
                self.overlay.set_property('offset-y', y_offset)
            else:
                self.overlay.set_property('relative-y', y_offset)

GObject.type_register(ImageSource)


class UriDecodebinSource(BaseInput):
    def __init__(self, location=None, name=None, width=None, height=None):
        BaseInput.__init__(self)
        if name:
            self.set_property('name', name)

        self.__build_audio_pipeline()
        self.__build_video_pipeline()

        decodebin = Gst.ElementFactory.make('uridecodebin', 'Decodebin Source (decodebin)')
        self.add(decodebin)
        decodebin.connect('pad-added', self.__pad_add_cb)
        decodebin.set_property('uri', location)
        self.decodebin = decodebin

        agpad = Gst.GhostPad.new('audiosrc', self.aq.get_static_pad('src'))
        vgpad = Gst.GhostPad.new('videosrc', self.vq.get_static_pad('src'))

        self.add_pad(agpad)
        self.add_pad(vgpad)

        self.set_geometry(width, height)


    def do_handle_message(self, message):
        if not message:
            return
        # we can be called at any time, so when playing for the first time seek to the begining unless
        # it is a user initiated pause.
        # FIXME: When resuming watch out for time changes.
        if message.type == Gst.MessageType.STATE_CHANGED and message.src is self.decodebin:
            prev, new, pending = message.parse_state_changed()
            if new == Gst.State.PAUSED and prev == Gst.State.READY:
                self._on_error = False
                def cb(*args):
                    self.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)
                    return False
                GLib.idle_add(cb)
                return

        BaseInput.do_handle_message(self, message)

    def __pad_add_cb(self, element, newpad):
        for el in [self.vrate, self.arate]:
            sink = el.get_compatible_pad(newpad, newpad.get_pad_template_caps())
            if sink and not sink.is_linked():
                newpad.link(sink)
                break

    def __build_audio_pipeline(self):
        aq    = Gst.ElementFactory.make('queue2', 'DecodebinSource Audio Q')
        aconv = Gst.ElementFactory.make('audioconvert', 'DecodebinSource audioconvert ')
        arate = Gst.ElementFactory.make('audiorate', 'DecodebinSource audiorate')
        avol  = Gst.ElementFactory.make('volume', 'DecodebinSource volume')

        for el in [aq, aconv, arate, avol]:
            self.add(el)

        arate.link(aconv)
        aconv.link(avol)
        avol.link(aq)

        self.aq = aq
        self.arate = arate
        self.volume = avol


    def __build_video_pipeline(self):
        vq    = Gst.ElementFactory.make('queue2', 'DecodebinSource Video Q')
        vconv = Gst.ElementFactory.make('videoconvert', 'DecodebinSource videoconvert ')
        vrate = Gst.ElementFactory.make('videorate', 'DecodebinSource videorate')

        vscale = Gst.ElementFactory.make('videoscale', 'DecodebinSource videoscale')
        vscale.set_property('add-borders', True)

        vcaps = Gst.ElementFactory.make('capsfilter', 'DecodebinSource videocaps')

        for el in [vq, vconv, vrate, vscale, vcaps]:
            self.add(el)

        vrate.link(vconv)
        vconv.link(vscale)
        vscale.link(vcaps)
        vcaps.link(vq)

        self.vq = vq
        self.vrate = vrate
        self.vconv = vconv
        self.vcaps = vcaps

GObject.type_register(UriDecodebinSource)

ALL_PROBES = [C920Probe]


class InputMonitor(GObject.GObject):
    __gsignals__ = {
       "added": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT]),
    }
    def __init__(self):
        from pyudev.glib import MonitorObserver
        GObject.GObject.__init__(self)
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem='video4linux')
        self.observer = MonitorObserver(self.monitor)
        self.observer.connect('device-event', self.__device_event)

    def start(self):
        self.monitor.start()

    def __device_event(self, observer, device):
        if device.action == 'add':
            logging.debug('DEVICE ADD: %s', device)
            for probe in ALL_PROBES:
                ret = probe(device, self.context)
                if ret:
                    logging.debug('PROBING OK: %s', ret)
                    self.emit('added', ret[0], ret[1])
                    return True
        return True

    def get_devices(self):
        devices = []

        context = pyudev.Context()
        cameras = context.list_devices().match_subsystem('video4linux')
        for device in cameras:
            for probe in ALL_PROBES:
                ret = probe(device, context)
                if ret:
                    devices.append(ret)
                    break

        #devices.append( (TestInput, {}) )
        return devices

class SoundCardMonitor(GObject.GObject):
    __gsignals__ = {
       "add": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
       "change": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
       "remove": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
    }
    def __init__(self):
        from pyudev.glib import MonitorObserver
        GObject.GObject.__init__(self)
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem='sound')
        self.observer = MonitorObserver(self.monitor)
        self.observer.connect('device-event', self.__device_event)

    def start(self):
        self.monitor.start()

    def __device_event(self, observer, device):
        action = device.action
        if action in ['add', 'change']:
            logging.debug('SOUND DEVICE %s: %s', action, device)
            if 'id' in device.attributes:
                c = {
                    'id': device.attributes['id'],
                    'model': device.get('ID_MODEL', ''),
                    'model_db': device.get('ID_MODEL_FROM_DATABASE', ''),
                    'path': device.get('DEVPATH', '')
                }
                self.emit(action, c)

        elif action == 'remove':
            logging.debug('SOUND DEVICE %s: %s', action, device)
            c = {
                'path': device.get('DEVPATH', '')
            }
            self.emit(action, c)
        return True

    def get_devices(self):
        context = pyudev.Context()
        cards = context.list_devices().match_subsystem('sound')
        devs = []
        for device in cards:
            if 'id' in device.attributes:
                c = {
                    'id': device.attributes['id'],
                    'model': device.get('ID_MODEL', ''),
                    'model_db': device.get('ID_MODEL_FROM_DATABASE', ''),
                    'path': device.get('DEVPATH', '')
                }
                devs.append(c)
        return devs

if __name__=='__main__':
    def add_cb(imon, arg, arg1):
        print 'ADD CB ', imon, arg, arg1

    def smon_cb(imon, c):
        print 'SOUND MON CB ', imon, c

    simon = SoundCardMonitor()
    print 'Sound cards: ', simon.get_devices()
    simon.connect('add', smon_cb)
    simon.connect('change', smon_cb)
    simon.connect('remove', smon_cb)
    simon.start()

    imon = InputMonitor()
    imon.connect('added', add_cb)
    imon.start()
    devices = imon.get_devices()

    #devices.append( (TestInput, {}) )
    p = Gst.Pipeline.new('P')
    for (src, props) in devices:
        print src, props
        src = src(**props)

        vsink = Gst.ElementFactory.make('xvimagesink', None)
        vsink.set_property('sync', False)
        asink = Gst.ElementFactory.make('autoaudiosink', None)

        p.add(src)
        p.add(asink)
        p.add(vsink)

        src.link(asink)
        src.link(vsink)

    p.set_state(Gst.State.PLAYING)
    Gst.debug_bin_to_dot_file(p, Gst.DebugGraphDetails.NON_DEFAULT_PARAMS | Gst.DebugGraphDetails.MEDIA_TYPE , 'debug_input')

    loop = GLib.MainLoop()
    loop.run()
