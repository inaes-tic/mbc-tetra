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
    _elem_type = 'source'
    def __init__(self, name=None, width=None, height=None):
        BaseArchivable.__init__(self)
        self.volume = None
        self.xvsink = None
        self.level = None
        self.vcaps = None
        self._geometries = deque()
        self._current_geometry = (width, height)
        self._on_error = False
        self._on_error_lck = threading.Lock()

        if name:
            self.set_property('name', name)

        self.push_geometry(width, height)

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

        self._current_geometry = (width,height)
        caps = Gst.Caps.from_string(tmpl)
        if caps:
            self.vcaps.set_property('caps', caps)
            return True

    def push_geometry(self, width=None, height=None):
        self._geometries.append(self._current_geometry)
        self.set_geometry(width, height)

    def pop_geometry(self):
        logging.debug('GEOMS: %s', self._geometries)
        try:
            new = self._geometries.pop()
            self.set_geometry(*new)
        except IndexError:
            return

    def set_mute(self, mute):
        if self.volume is None:
            return
        self.volume.set_property('mute', mute)

    def initialize(self):
        pass

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


class C920Input(BaseInput):
    _mux_pad_names = ['video_%u', 'audio_%u']
    filename_suffix = '.mkv'
    def __init__(self, video_props, audio_props, name=None, serial='', *args, **kwargs):
        BaseInput.__init__(self, name=name, width=VIDEO_WIDTH, height=VIDEO_HEIGHT)

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

    def do_state_changed(self, prev, curr, new):
        if curr == Gst.State.PAUSED:
            self.set_geometry(*self._current_geometry)

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
        streamvt = Gst.ElementFactory.make ('tee', None)
        vconv = Gst.ElementFactory.make ('videoconvert', None)
        vscale = Gst.ElementFactory.make ('videoscale', None)
        vcaps = Gst.ElementFactory.make ('capsfilter', None)
        sink = Gst.ElementFactory.make ('xvimagesink', None)
        sink.set_property('sync', XV_SYNC)

        self.xvsink = sink
        self.vsrc = src
        self.vcaps = vcaps

        for el in (src, sink, q0, q1, q2, streamvt, tee, parse, dec, vconv, vscale, vcaps):
            self.add(el)

        if props:
            for prop,val in props.items():
                src.set_property(prop, val)

# XXX:
        #q0.set_property ('max-size-time', int(1*Gst.SECOND))
        src.link(q0)
        q0.link_filtered(streamvt, VIDEO_CAPS)
        streamvt.link_filtered(parse, VIDEO_CAPS)
        parse.link(dec)
        dec.link(tee)
        tee.link(q1)
        tee.link(q2)
        q2.link(sink)
        q1.link(vconv)
        vconv.link(vscale)
        vscale.link(vcaps)
        self.vsink = vcaps
        self.vtee = tee

        self.add_stream_writer_source(streamvt)

    def __add_audio_source (self, props):
        props.update(AUDIO_PROPS)
        C920_AUDIO_CAPS = Gst.Caps.from_string ('audio/x-raw,format=S16LE,rate=32000,channels=2')
        name = props.get('name', 'alsasrc')
        src = Gst.ElementFactory.make (name, None)
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
        fasink.set_property ('sync', True)
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

        src.link_filtered (q0, C920_AUDIO_CAPS)
        q0.link (volume)
        volume.link (tee)
        tee.link (q1)
        tee.link (q3)
        #tee.link (streamaq)
        q3.link (aconv2)
        aconv2.link(ares)
        ares.link_filtered(q2, AUDIO_CAPS)
        q1.link (aconv)
        aconv.link (flt)
        flt.link (level)
        level.link(fasink)

        self.add_stream_writer_source(tee)

GObject.type_register(C920Input)


def C920Probe(device, context):
    model = device.get('ID_MODEL', None)
    if model not in  [u'HD_Pro_Webcam_C920', u'0821']:
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
        BaseInput.__init__(self, name=name)

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
        BaseInput.__init__(self, name=name)

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
        fasink.set_property ('sync', True)
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
        BaseInput.__init__(self, name=name, width=width, height=height)

        self.__build_audio_pipeline()
        self.__build_video_pipeline()

        decodebin = Gst.ElementFactory.make('uridecodebin', 'Decodebin Source (decodebin)')
        self.add(decodebin)
        decodebin.connect('pad-added', self.__pad_add_cb)
        decodebin.set_property('uri', location)
        decodebin.set_property('use-buffering', True)
        self.decodebin = decodebin

        agpad = Gst.GhostPad.new('audiosrc', self.aq.get_static_pad('src'))
        vgpad = Gst.GhostPad.new('videosrc', self.vq.get_static_pad('src'))

        self.add_pad(agpad)
        self.add_pad(vgpad)

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

class InterSource(BaseInput):
    def __init__(self, name=None, channel='channel-1'):
        BaseInput.__init__(self, name=name)

        self.channel = channel
        self.__build_audio_pipeline()
        self.__build_video_pipeline()


        agpad = Gst.GhostPad.new('audiosrc', self.aq.get_static_pad('src'))
        vgpad = Gst.GhostPad.new('videosrc', self.vq.get_static_pad('src'))

        self.add_pad(agpad)
        self.add_pad(vgpad)

    def __build_audio_pipeline(self):
        #XXX UGLY HACK: interaudiosrc reports itself as being live source with a fixed and big latency.
        # that delays the whole pipeline, so we changed gstinteraudiosrc.c to set min and max latency
        # to 5 buffers instead of the default of 30.
        aq    = Gst.ElementFactory.make('queue2', 'InterSource Audio Q')
        aint  = Gst.ElementFactory.make('interaudiosrc', 'InterSource interaudiosrc')
        aint.set_property('channel', self.channel)
        aint.set_property('do-timestamp', True)

        for el in [aq, aint]:
            self.add(el)

        aint.link(aq)
        self.aq = aq



    def __build_video_pipeline(self):
        vq    = Gst.ElementFactory.make('queue2', 'InterSource Video Q')
        vint  = Gst.ElementFactory.make('intervideosrc', 'InterSource intervideosrc')
        vcaps = Gst.ElementFactory.make('capsfilter', 'InterSource videocaps')

        vcaps.set_property('caps', VIDEO_CAPS_SIZE)

        vint.set_property('channel', self.channel)
        vint.set_property('do-timestamp', True)
        vint.set_property('typefind', True)

        for el in [vq, vint, vcaps]:
            self.add(el)

        vint.link(vcaps)
        vcaps.link(vq)
        self.vq = vq

GObject.type_register(InterSource)


class InterPlayer(GObject.GObject):
    __gsignals__ = {
       "state-changed": (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT)),
       "eos": (GObject.SIGNAL_RUN_FIRST, None, []),
       "playing": (GObject.SIGNAL_RUN_FIRST, None, []),
       "paused": (GObject.SIGNAL_RUN_FIRST, None, []),
       "stopped": (GObject.SIGNAL_RUN_FIRST, None, []),
       "level": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
    }

    def __init__(self, channel='channel-1'):
        GObject.GObject.__init__(self)
        self.channel = channel
        self.pipeline = None

    def play_uri(self, uri):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

        channel = self.channel
        desc = 'uridecodebin name=dbin ! videoscale add-borders=true ! videorate ! %s ! queue2 ! intervideosink name=interv channel=%s dbin. ! audio/x-raw ! queue2 ! level ! audioconvert ! audioresample ! interaudiosink name=intera channel=%s' % (VIDEO_CAPS_SIZE.to_string(), channel, channel)

        p = Gst.parse_launch(desc)
        dbin = p.get_by_name('dbin')
        dbin.set_property('uri', uri)
        self.pipeline = p

        bus = self.bus = p.get_bus()
        bus.add_signal_watch()
        bus.connect("message::state-changed", self.bus_state_changed_cb)
        bus.connect("message::element", self.bus_element_cb)
        bus.connect("message", self.bus_message_cb)
        self._last_state = [None, None, None]
        p.set_state(Gst.State.PLAYING)

    def play_pause(self, pause=None):
        if self.pipeline is None:
            return

        state = self.pipeline.get_state(0)[1]
        if state not in [Gst.State.PLAYING, Gst.State.PAUSED]:
            return

        if pause is None:
            pause = (state == Gst.State.PLAYING)

        if pause:
            self.pipeline.set_state(Gst.State.PAUSED)
        else:
            self.pipeline.set_state(Gst.State.PLAYING)

    def seek(self, position=0):
        if self.pipeline is None:
            return

        dbin = self.pipeline.get_by_name('dbin')
        ok, total = self.pipeline.query_duration(Gst.Format.TIME)
        if not ok:
            return
        position = 0.01 * position * total
        logging.debug('InterPlayer SEEK TOTAL TIME: %s, REQ:%s', total, position)
        dbin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, position)

    def bus_message_cb (self, bus, msg, arg=None):
        if msg.type == Gst.MessageType.EOS:
            self.emit('eos')

        return True

    def bus_state_changed_cb (self, bus, msg, arg=None):
        if msg.src != self.pipeline:
            return True
        prev, new, pending = msg.parse_state_changed()
        curr_state = [prev, new, pending]
        if new != self._last_state[1]:
            self.emit('state-changed', prev, new, pending)

            name = {
                Gst.State.PLAYING: 'playing',
                Gst.State.PAUSED:  'paused',
                Gst.State.NULL:    'stopped',
            }.get(new, None)
            if name:
                self.emit(name)
        logging.debug('InterPlayer STATE CHANGE: %s', curr_state)
        self._last_state = curr_state

        return True

    def bus_element_cb (self, bus, msg, arg=None):
        if msg.get_structure() is None:
            return True

        s = msg.get_structure()
        if s.get_name() == "level":
            arms = s.get_value('rms')
            larms = len(arms)
            if larms:
                rms = sum (arms) / larms
                self.emit('level', arms)
        return True

GObject.type_register(InterPlayer)

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
