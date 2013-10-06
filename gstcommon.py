#!/usr/bin/env python

import logging

import threading
import gi
gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst

class BaseBin(Gst.Bin):
    __gsignals__ = {
       "removed": (GObject.SIGNAL_RUN_FIRST, None, []),
    }
    _elem_type = 'source'

    def __init__(self):
        Gst.Bin.__init__(self)
        self._on_unlink = False
        self._on_unlink_lck = threading.Lock()
        self._probes = {}
        self._pads_to_block = []

    def __contains__ (self, item):
        return item in self.children

    def disconnect_element(self):
        # In order to properly remove ourselves from the pipeline we need to block the
        # pads, when all of them are blocked we can safely unlink *from the main thread*
        # (that's what the element message is for, when we receive it on the bus handler we
        # call do_unlink() on the source of the message).
        #
        # If we are a source we block our pads and release their peers if needed.
        # If we are a sink we block our peers and release them if needed.
        #
        # However, if no buffers are currently flowing (or won't be) the probe never succedes.
        # Common wisdom suggest to use a custom event but, if we are in a null state
        # (like, we tried to open a non-existing device upon starting), this will also fail.
        # So in that case we just unlink and hope for the best.
        state = self.get_state(0)
        logging.debug('DISCONNECT ELEMENT CURRENT STATE %s', state)

        if self._elem_type == 'source':
            self._pads_to_block = list(self.pads)
        else:
            self._pads_to_block = [pad.get_peer() for pad in self.pads]

        ok = True
        for pad in self._pads_to_block:
            if not pad:
                continue
            if pad.is_blocked() == False:
                ok = False
                if pad not in self._probes:
                    self._probes[pad] = pad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM | Gst.PadProbeType.BLOCK_UPSTREAM, self.pad_block_cb, None)
                    logging.debug('DISCONNECT ELEMENT ADD PAD PROBE FOR %s PAD IS BLOCKED? %s PAD IS LINKED? %s', pad, pad.is_blocked(), pad.is_linked())

        if (ok or state[1] in [Gst.State.NULL, Gst.State.PAUSED]):
            self._on_unlink = True
            logging.debug('PAD BLOCK, state NULL or PAUSED. signal ready-to-unlink')
            self._send_element_message('ready-to-unlink')
        return False

    def do_unlink (self, *args):
        self.__unlink_and_set_to_null ()

    def __unlink_and_set_to_null (self):
        parent = self.get_parent()
        logging.debug('SET EL %s TO NULL %s', self, self.set_state(Gst.State.NULL))

        for pad in self._pads_to_block:
            peer = pad.get_peer()
            if peer is not None:
                logging.debug('UNLINK PAD %s', pad)
                pad.unlink(peer)

                if self._elem_type == 'source':
                    parent = peer.get_parent()
                else:
                    parent = pad.get_parent()
                    peer = pad

                presence = None
                tmpl = peer.get_pad_template()
                if tmpl:
                    presence = tmpl.presence
                if parent and (presence == Gst.PadPresence.REQUEST):
                    logging.debug('BEFORE PAD PARENT RELEASE PAD')
                    parent.release_request_pad(peer)
                    logging.debug('PAD PARENT RELEASE PAD OK')

        logging.debug('SET EL TO NULL OK? %s', self)

        self._send_element_message('unlinked')
        self.emit('removed')

        return False

    def _send_element_message(self, name):
        s = Gst.Structure.new_empty(name)
        msg = Gst.Message.new_element(self, s)
        self.post_message(msg)

    def pad_block_cb(self, pad, probe_info, data=None):
        ok = True
        for pad in self._pads_to_block:
            if not pad:
                continue
            if pad.is_blocked() == False:
                ok = False
        if ok:
            if self._on_unlink_lck.acquire(True):
                if not self._on_unlink:
                    self._on_unlink = True
                    logging.debug('PAD BLOCK signal ready-to-unlink')
                    s = Gst.Structure.new_empty('ready-to-unlink')
                    msg = Gst.Message.new_element(self, s)
                    self.post_message(msg)

                self._on_unlink_lck.release()

        return Gst.PadProbeReturn.DROP

