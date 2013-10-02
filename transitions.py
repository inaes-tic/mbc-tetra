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
from gi.repository import GstController
from gi.repository import GLib


from common import *

class BaseTransition(GObject.Object):
    def __init__(self, *args):
        GObject.GObject.__init__(self)
        self.current_input = None

    def set_active_input_by_source(self, source, *args, **kwargs):
        raise NotImplemented

    def start_pip(self, source, position="LR", *args, **kwargs):
        raise NotImplemented

    def stop_pip(self, source):
        raise NotImplemented

class InputSelectorTransition(BaseTransition):
    def __init__(self, *args):
        BaseTransition.__init__(self)

        self.mixer = Gst.ElementFactory.make('input-selector', 'InputSelectorTransition input-selector')

    def set_active_input_by_source(self, source, *args, **kwargs):
        peers = [pad.get_peer() for pad in source.pads]

        mixer = self.mixer
        oldpad = mixer.get_property ('active-pad')

        if oldpad in peers:
            return

        for pad in mixer.sinkpads:
            if pad in peers:
                logging.info('InputSelectorTransition: set active input by source ok')
                mixer.set_property('active-pad', pad)
                self.current_input = source
                return source

class VideoMixerTransition(BaseTransition):
    PIP_LAYER = 10
    BG_LAYER = 0
    FG_CUR_LAYER = 3
    FG_PREV_LAYER = 2
    def __init__(self, *args):
        BaseTransition.__init__(self)

        self.pip_pads = []

        self.mixer = Gst.ElementFactory.make('videomixer', 'VideoMixerTransition videomixer')
        self.mixer.set_property('background', 'black')

        self.transitions = {
            None: self.fast_switch,
            False: self.fast_switch,
            'fast': self.fast_switch,
            'blend': self.alpha_blend,
            'slide_lr': self.slide_lr,
            'slide_rl': self.slide_rl,
        }

    def get_mixerpad_for_source(self, source):
        mixerpad = None
        if not source:
            return None

        peers = [pad.get_peer() for pad in source.pads]

        for pad in self.mixer.sinkpads:
            if pad in peers:
                mixerpad = pad
                break
        return mixerpad

    def set_active_input_by_source(self, source, transition='fast', duration=0.25):
        if source == self.current_input:
            transition = False

        mixer = self.mixer
        current_pad = None
        previous_pad = None

        if self.current_input:
            previous_pad = self.get_mixerpad_for_source(self.current_input)

        current_pad = self.get_mixerpad_for_source(source)
        # probably it would be better if we just turn of PiP for the source.
        if current_pad in self.pip_pads:
            return

        for pad in mixer.sinkpads:
            if pad in self.pip_pads:
                continue
            if pad is current_pad:
                continue

            if pad is not previous_pad:
                self._reset_pad(pad, {'alpha':0})
            pad.set_property('zorder', self.FG_PREV_LAYER)

        if current_pad:
            current_pad.set_property('zorder', self.FG_CUR_LAYER)
            if previous_pad is None:
                self._reset_pad(current_pad, {'alpha':1, 'xpos':0, 'ypos':0})
                logging.debug('VideoMixerTransition: previous_pad is None')
            elif previous_pad is current_pad:
                self._reset_pad(current_pad, {'alpha':1, 'xpos':0, 'ypos':0})
                logging.debug('VideoMixerTransition: previous_pad is current_pad')
            else:
                if transition:
                    self.transitions.get(transition, self.alpha_blend)(previous_pad, current_pad, duration=duration)
                else:
                    self.fast_switch(previous_pad, current_pad)

            self.current_input = source
            logging.info('VideoMixerTransition: set active input by source ok using %s', transition)
            return source

    def start_pip(self, source, position="LR", *args, **kwargs):
        position = position.upper().strip()
        # Top Center Bottom, Left Right
        if position not in "TR CR BR TL CL BL TC CC BC".split():
            position = "BR"

        pad = self.get_mixerpad_for_source(source)
        logging.debug('START PiP, SOURCE: %s, PAD: %s, POS: %s', source, pad, position)
        if pad is None:
            return

        if pad not in self.pip_pads:
            self.pip_pads.append(pad)
            self._reset_pad(pad, {'alpha':0, 'zorder':self.PIP_LAYER})
            source.set_geometry(VIDEO_WIDTH/3, VIDEO_HEIGHT/3)
            if source is self.current_input:
                self.current_input = None

        y,x = position

        xpos = {
            'L': 0,
            'C': VIDEO_WIDTH/3,
            'R': 2*VIDEO_WIDTH/3,
        }[x]

        ypos = {
            'T': 0,
            'C': VIDEO_HEIGHT/3,
            'B': 2*VIDEO_HEIGHT/3,
        }[y]

        self._reset_pad(pad, {'alpha':0, 'xpos':xpos, 'ypos':ypos})
        self._reset_pad(pad, {'alpha':1})
        logging.debug('START PiP, xpos: %i, ypos: %i', xpos, ypos)

    def stop_pip(self, source):
        pad = self.get_mixerpad_for_source(source)
        if pad is None:
            return

        if pad not in self.pip_pads:
            return

        # back to original size
        source.set_geometry()
        self._reset_pad(pad, {'alpha':1, 'xpos':0, 'ypos':0})
        self.pip_pads.remove(pad)
        self.current_input = source

    def _get_control_source(self, elem, prop='alpha'):
        ctrl = elem.get_control_binding(prop)
        if ctrl:
            return ctrl.get_property('control_source')
        cs = GstController.InterpolationControlSource()
        cs.set_property('mode', GstController.InterpolationMode.LINEAR)
        cb = GstController.DirectControlBinding.new(elem, prop, cs)
        elem.add_control_binding(cb)
        return cs

    def _reset_pad(self, pad, props=None):
        for prop in ['alpha', 'xpos', 'ypos']:
            cs = self._get_control_source(pad, prop)
            cs.unset_all()
        if props:
            for prop,value in props.items():
                pad.set_property(prop, value)

    def alpha_blend(self, old_pad, new_pad, duration=0.25):
        now = self.mixer.get_clock().get_time() # XXX: you better check for errors
        end = now + duration*Gst.SECOND

        self._reset_pad(old_pad, {'xpos':0, 'ypos':0, 'zorder': self.FG_PREV_LAYER})
        self._reset_pad(new_pad, {'xpos':0, 'ypos':0, 'zorder': self.FG_CUR_LAYER})

        new_alpha = self._get_control_source(new_pad)
        old_alpha = self._get_control_source(old_pad)

        new_alpha.set(now, 0)
        old_alpha.set(now, 1)
        new_alpha.set(end, 1)
        old_alpha.set(end, 0)

    def fast_switch(self, old_pad, new_pad, duration=None):
        self._reset_pad(old_pad, {'alpha':0, 'xpos':0, 'ypos':0})
        self._reset_pad(new_pad, {'alpha':1, 'xpos':0, 'ypos':0})
        logging.debug('VideoMixerTransition: do fast_switch')

    def horiz_slide(self, old_pad, new_pad, direction="LR", duration=0.25):
        def coord_to_controller(coord):
            # the controller interface maps [0..1] to the property range, in
            # this case [-2147483647, 2147483648]
            return 0.5*(1 + 1.0*coord/2147483647)

        self._reset_pad(old_pad, {'xpos':0, 'ypos':0, 'alpha':1})
        self._reset_pad(new_pad, {'xpos':0, 'ypos':0, 'alpha':0})

        if direction not in ["LR", "RL"]:
            direction = "LR"

        now = self.mixer.get_clock().get_time() # XXX: you better check for errors
        end = now + duration*Gst.SECOND

        if direction == "LR":
            new_startx = -VIDEO_WIDTH
            old_endx = VIDEO_WIDTH
        else:
            new_startx = VIDEO_WIDTH
            old_endx = -VIDEO_WIDTH

        new_startx = coord_to_controller(new_startx)
        old_endx = coord_to_controller(old_endx)
        defaultx = 0.5

        new_xcs = self._get_control_source(new_pad, "xpos")
        old_xcs = self._get_control_source(old_pad, "xpos")
        old_alpha = self._get_control_source(old_pad, "alpha")

        old_xcs.set(now, defaultx)
        new_xcs.set(now, new_startx)

        old_xcs.set(end, old_endx)
        old_alpha.set(end, 0)
        new_xcs.set(end, defaultx)

        new_pad.set_property('alpha', 1)

    def slide_lr(self, old_pad, new_pad, duration=0.25):
        return self.horiz_slide(old_pad, new_pad, direction="LR", duration=duration)

    def slide_rl(self, old_pad, new_pad, duration=0.25):
        return self.horiz_slide(old_pad, new_pad, direction="RL", duration=duration)

