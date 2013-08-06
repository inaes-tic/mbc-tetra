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
    def __init__(self, *args):
        BaseTransition.__init__(self)

        self.mixer = Gst.ElementFactory.make('videomixer', 'VideoMixerTransition videomixer')
        self.mixer.set_property('background', 'black')

        self.transitions = {
            None: self.fast_switch,
            False: self.fast_switch,
            'fast': self.fast_switch,
            'blend': self.alpha_blend,
        }

    def set_active_input_by_source(self, source, transition=True):
        if source == self.current_input:
            transition = False

        mixer = self.mixer
        old_pads = []
        current_pad = None
        previous_pad = None

        if self.current_input:
            peers = [pad.get_peer() for pad in self.current_input.pads]
            for pad in mixer.sinkpads:
                if pad in peers:
                    previous_pad = pad
                    break

        peers = [pad.get_peer() for pad in source.pads]
        for pad in mixer.sinkpads:
            if pad in peers:
                current_pad = pad
                pad.set_property('zorder', 2)
            else:
                old_pads.append(pad)
                if pad is not previous_pad:
                    pad.set_property('alpha', 0)
                    pad.set_property('zorder', 3)
                    for prop in ['alpha', 'xpos', 'ypos']:
                        cs = self._get_control_source(pad, prop)
                        cs.unset_all()
        if current_pad:
            if previous_pad is None:
                current_pad.set_property('alpha', 1)
                current_pad.set_property('zorder', 2)
                logging.debug('VideoMixerTransition: previous_pad is None')
            elif previous_pad is current_pad:
                current_pad.set_property('alpha', 1)
                current_pad.set_property('zorder', 2)
                logging.debug('VideoMixerTransition: previous_pad is current_pad')
            else:
                if transition:
                    self.transitions.get(transition, self.alpha_blend)(previous_pad, current_pad)
                else:
                    self.fast_switch(previous_pad, current_pad)

            self.current_input = source
            logging.info('VideoMixerTransition: set active input by source ok using %s', transition)
            return source

    def _get_control_source(self, elem, prop='alpha'):
        ctrl = elem.get_control_binding(prop)
        if ctrl:
            return ctrl.get_property('control_source')
        cs = GstController.InterpolationControlSource()
        cs.set_property('mode', GstController.InterpolationMode.LINEAR)
        cb = GstController.DirectControlBinding.new(elem, prop, cs)
        elem.add_control_binding(cb)
        return cs

    def alpha_blend(self, old_pad, new_pad):
        now = self.mixer.get_clock().get_time() # XXX: you better check for errors
        end = now + 0.25*Gst.SECOND

        new_alpha = self._get_control_source(new_pad)
        old_alpha = self._get_control_source(old_pad)

        new_alpha.unset_all()
        old_alpha.unset_all()

        old_pad.set_property('zorder', 3)
        new_alpha.set(now, 0)
        old_alpha.set(now, 1)
        new_alpha.set(end, 1)
        old_alpha.set(end, 0)

    def fast_switch(self, old_pad, new_pad):
        old_pad.set_property('alpha', 0)
        old_pad.set_property('zorder', 3)
        new_pad.set_property('alpha', 1)
        new_pad.set_property('zorder', 2)
        logging.debug('VideoMixerTransition: do fast_switch')

