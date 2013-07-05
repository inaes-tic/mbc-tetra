#!/usr/bin/env python

import logging

import time
import sys
import os
from collections import deque
from itertools import ifilter


import gi
gi.require_version('Gst', '1.0')

from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstVideo
from gi.repository import GLib

## FIXME: tamano real mas luego.
## VIDEO_CAPS = Gst.Caps.from_string ('image/jpeg,width=320,rate=30,framerate=30/1')
## VIDEO_CAPS = Gst.Caps.from_string ('image/jpeg,width=1024,rate=30,framerate=30/1')
VIDEO_CAPS = Gst.Caps.from_string ('image/jpeg,width=800,heigth=448,rate=30,framerate=30/1')
AUDIO_CAPS = Gst.Caps.from_string ('audio/x-raw,format=S16LE,rate=32000,channels=2')

XV_SYNC=False

class GeneralInputError(Exception):
    pass

class C920Input(Gst.Bin):
    __gsignals__ = {
       "removed": (GObject.SIGNAL_RUN_FIRST, None, []),
    }
    def __init__(self, video_props, audio_props, name=None):
        Gst.Bin.__init__(self)
        if name:
            self.set_property('name', name)
        self.asink = None
        self.vsink = None

        self.__add_video_source(video_props)
        self.__add_audio_source(audio_props)

        if not (self.asink and self.vsink):
            raise GeneralInputError('Cannot create audio or video source')

        agpad = Gst.GhostPad.new('audiosrc', self.asink.get_static_pad('src'))
        vgpad = Gst.GhostPad.new('videosrc', self.vsink.get_static_pad('src'))

        self.add_pad(agpad)
        self.add_pad(vgpad)

    def __contains__ (self, item):
        return item in self.children

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

    def __add_video_source (self, props):
# XXX FIXME: cambiar el jpeg por raw mas luego.
        name = props.get('name', 'v4l2src')
        src = Gst.ElementFactory.make (name, None)
        q0 = Gst.ElementFactory.make ('queue2', None)
        tee = Gst.ElementFactory.make ('tee', None)
        parse = Gst.ElementFactory.make ('jpegparse', None)
        dec = Gst.ElementFactory.make ('jpegdec', None)
        q1 = Gst.ElementFactory.make ('queue2', None)
        q2 = Gst.ElementFactory.make ('queue2', None)
        sink = Gst.ElementFactory.make ('xvimagesink', None)
        sink.set_property('sync', XV_SYNC)

        self.xvsink = sink
        self.vsink = q1
        self.vsrc = src

        for el in (src, sink, q0, q1, q2, tee, parse, dec):
            self.add(el)

        if props:
            for prop,val in props.items():
                src.set_property(prop, val)

# XXX:
        #q0.set_property ('max-size-time', int(1*Gst.SECOND))
        src.link(q0)
        q0.link_filtered(parse, VIDEO_CAPS)
        parse.link(dec)
        dec.link(tee)
        tee.link(q1)
        tee.link(q2)
        q2.link(sink)


    def __add_audio_source (self, props):
        name = props.get('name', 'alsasrc')
        src = Gst.ElementFactory.make (name, None)
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
        aconv = Gst.ElementFactory.make ('audioconvert', None)

        flt = Gst.ElementFactory.make ('audiochebband', None)
        flt.set_property ('lower-frequency', 400)
        flt.set_property ('upper-frequency', 3500)
        # 10 samples per second
        level = Gst.ElementFactory.make ('level', None)
        level.set_property ("message", True)
        self.level = level

        for el in (src, q0, q1, q2, tee, volume, fasink, aconv, flt, level):
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
        q1.link (aconv)
        aconv.link (flt)
        flt.link (level)
        level.link(fasink)

    def __unlink_and_set_to_null (self):
        parent = self.get_parent()
        if parent:
            logging.debug('SET EL TO NULL')
            self.set_state(Gst.State.NULL)
            for element in self.children:
                element.set_state(Gst.State.NULL)

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

        logging.debug('SET EL TO NULL OK?')

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
            GLib.timeout_add(0, self.__unlink_and_set_to_null)

        return Gst.PadProbeReturn.REMOVE

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
            GLib.timeout_add(0, self.__unlink_and_set_to_null)
            return

        ok = True
        for pad in self.pads:
            if pad.is_blocked() == False:
                ok = False
            logging.debug('DISCONNECT SOURCE ADD PAD PROBE FOR %s PAD IS BLOCKED? %s PAD IS LINKED? %s', pad, pad.is_blocked(), pad.is_linked())
            pad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM | Gst.PadProbeType.BLOCK_UPSTREAM, self.pad_block_cb, None)
        if ok:
            logging.debug('PAD BLOCK ADD IDLE')
            GLib.timeout_add(0, self.__unlink_and_set_to_null)


if __name__=='__main__':
    GObject.threads_init()
    Gst.init(sys.argv)

    aprops = { }
    vprops = { }

    p = Gst.Pipeline.new('P')

    inp = C920Input(vprops, aprops)

    vsink = Gst.ElementFactory.make('xvimagesink', None)
    vsink.set_property('sync', False)
    asink = Gst.ElementFactory.make('fakesink', None)

    p.add(inp)
    p.add(asink)
    p.add(vsink)

    inp.link(asink)
    inp.link(vsink)

    p.set_state(Gst.State.PLAYING)
    Gst.debug_bin_to_dot_file(p, Gst.DebugGraphDetails.NON_DEFAULT_PARAMS | Gst.DebugGraphDetails.MEDIA_TYPE , 'debug_input')

    loop = GLib.MainLoop()
    loop.run()