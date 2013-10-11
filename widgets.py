#!/usr/bin/env python

import logging

import os
import sys
import time
from collections import deque

import gi

from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gst
from gi.repository import GstVideo
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkX11

import config
from common import *

import input_sources


class SoundMixWidget(Gtk.Box):
    __gsignals__ = {
       "set-mix-source": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
       "set-mix-device": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
    }
    def __init__(self):
        Gtk.Box.__init__(self)

        self.config = config.get('output_mix', {})
        self.builder = Gtk.Builder ()
        self.builder.add_objects_from_file ('audio_widget.ui', ['CardWidget', 'cards_store'])
        self.mainwidget = self.builder.get_object('CardWidget')
        self.add(self.mainwidget)

        self.ext_mix_r = self.builder.get_object('ext_mix_r')
        self.combo = self.builder.get_object('cards')

        self.imon = input_sources.SoundCardMonitor()
        self.cards = self.imon.get_devices()

        mixtype = self.config.setdefault('mix-source', 'internal')
        if mixtype != 'internal':
            self.ext_mix_r.set_active(True)
            self.combo.set_sensitive(True)
        self.ext_mix_r.connect('toggled', self.mix_tog)
        self.mix_source = mixtype

        active_card = self.config.setdefault('extern_card', 'default')
        self.mix_device = {'device': active_card, 'path':'', 'human_name':'default'}

        self.lstore = self.builder.get_object('cards_store')
        self.lstore.append(['default','default','default'])
        self.combo.set_model(self.lstore)
        self.combo.set_active(0)

        for idx,card in enumerate(self.cards):
            item = []
            human_name = '%s - %s - %s' % (card['id'], card['model'], card['model_db'])
            item.append(card['path'])
            cid = 'hw:CARD=%s' % card['id']
            item.append(cid)
            item.append(human_name)
            self.lstore.append(item)

            # idx 0 is the default device
            if cid == active_card:
                self.combo.set_active(idx+1)

        self.combo.connect('changed', self.combo_cb)

    def combo_cb(self, combo):
        citer = combo.get_active_iter()
        model = combo.get_model()
        path, cid, human_name = model[citer]
        device = {
            'path': path,
            'device': cid,
            'human_name': human_name
        }
        self.config['extern_card'] = cid
        self.mix_device = device
        self.emit('set-mix-device', device)

    def mix_tog(self, widget, *data):
        act = widget.get_active()
        self.combo.set_sensitive(act)
        source = {
            True: 'external',
            False: 'internal'
        }[act]
        self.mix_source = source
        self.emit('set-mix-source', source)
        self.config['mix-source'] = source


class PreviewWidget(Gtk.Box):
    __gsignals__ = {
       "mute": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT]),
       "volume": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT]),
       "preview-clicked": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
    }
    def __init__(self, source=None):
        Gtk.Box.__init__(self)
        builder = Gtk.Builder ()
        self.builder = builder
        self.source = source
        self.xid = None

        builder.add_objects_from_file (config.get('preview_ui','preview_box.ui'), ['PreviewBoxItem'])
        preview = builder.get_object('PreviewBoxItem')
        self.add(preview)

        slider = builder.get_object ('volume')
        slider.connect ("value-changed", self.__slider_cb)

        bars = []
        bar_l = builder.get_object ('peak_L')
        if bar_l:
            bars.append(bar_l)
        bar_r = builder.get_object ('peak_R')
        if bar_r:
            bars.append(bar_r)

        self.bars = bars

        mute = builder.get_object ('mute')
        mute.connect ("toggled", self.__mute_cb)

        self.set_source(source)
        self.connect('map', self.__map_event_cb)

    def set_source(self, source=None):
        if source:
            da = self.builder.get_object('preview')
            da.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.TOUCH_MASK)
            self.source = source
            da.connect('button-press-event', self.__preview_click_cb)
            da.show()
            spinner = self.builder.get_object('spinner')

            if spinner:
                self.builder.get_object('preview_container').remove(spinner)
                spinner.destroy()

            self.set_window_handle(safe=True)

    def set_window_handle(self, safe=False):
        if not self.source:
            return
        if safe:
            self.__get_xid()

        if self.xid is not None:
            Gdk.threads_enter ()
            self.source.xvsink.set_window_handle(self.xid)
            self.source.xvsink.set_property('sync', XV_SYNC)
            Gdk.threads_leave ()

    def set_levels (self, peaks):
        Gdk.threads_enter ()
        for bar,peak in zip(self.bars, peaks):
            frac = 1.0 - peak/MIN_PEAK
            if frac < 0:
                frac = 0
            elif frac > 1:
                frac = 1
            bar.set_fraction (frac)
        Gdk.threads_leave ()
        return True

    def __mute_cb(self, widget, *data):
        mute = widget.get_active()
        self.emit('mute', self.source, mute)
        if self.source:
            self.source.set_mute(mute)

    def __slider_cb(self, widget, value, *data):
        self.emit('volume', self.source, value)
        if self.source:
            self.source.set_volume(value)

    def __preview_click_cb (self, widget, event, *data):
        self.emit('preview-clicked', self.source)

    def __map_event_cb(self, *args):
        self.__get_xid()

    def __get_xid(self):
        da = self.builder.get_object('preview')
        window = da.get_property('window')
        if window:
            self.xid = window.get_xid()
        return True

class MasterMonitor(Gtk.Box):
    __gsignals__ = {
       "mute": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
       "volume": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
    }
    def __init__(self):
        Gtk.Box.__init__(self)
        builder = Gtk.Builder ()
        self.builder = builder

        builder.add_objects_from_file (config.get('mastermonitor_ui','master_monitor.ui'), ['MasterMonitor'])
        monitor = builder.get_object('MasterMonitor')
        self.add(monitor)

        slider = builder.get_object ('volume')
        slider.connect ("value-changed", self.__slider_cb)

        bars = []
        bar_l = builder.get_object ('peak_L')
        if bar_l:
            bars.append(bar_l)
        bar_r = builder.get_object ('peak_R')
        if bar_r:
            bars.append(bar_r)

        self.bars = bars

        mute = builder.get_object ('mute')
        mute.connect ("toggled", self.__mute_cb)

    def set_levels (self, peaks):
        Gdk.threads_enter ()
        for bar,peak in zip(self.bars, peaks):
            frac = 1.0 - peak/MIN_PEAK
            if frac < 0:
                frac = 0
            elif frac > 1:
                frac = 1
            bar.set_fraction (frac)
        Gdk.threads_leave ()
        return True

    def __mute_cb(self, widget, *data):
        mute = widget.get_active()
        self.emit('mute', mute)

    def __slider_cb(self, widget, value, *data):
        self.emit('volume', value)


class PipManager(Gtk.Box):
    __gsignals__ = {
        # camera idx, -1 for all.
        "switch": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
        "pip-off": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
        # camera idx, position.
        "pip-start": (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT]),

    }
    def __init__(self, *args, **kwargs):
        Gtk.Box.__init__(self)
        builder = Gtk.Builder ()
        self.builder = builder

        builder.add_objects_from_file (config.get('pip_ui','pipmgr.ui'), ['PipManager'])
        mgr = builder.get_object('PipManager')
        self.add(mgr)

        self._pip_idx = -1
        self.input_buffer = deque()
        self.state = 'switch'
        self.states = {
            'pip': self.pip,
            'pip_sel_cam': self.pip_sel_cam,
            'switch': self.switch,
        }

        for name in "TR CR BR TL CL BL TC CC BC".split():
            but = self.builder.get_object(name)
            if but:
                but.connect('clicked', self.pip_pos_but, name)
        for idx in range(3):
            but = self.builder.get_object('cam%d'%idx)
            if but:
                but.connect('clicked', self.pip_cam_but, idx)

        but = self.builder.get_object('clear_pip')
        but.connect('clicked', self.pip_stop_but)

    def pip_cam_but(self, widget, idx):
        if widget.get_active():
            self._pip_idx = idx
        else:
            self.emit('pip-off', idx)
            self._pip_idx = -1

    def pip_pos_but(self, widget, pos):
        if self._pip_idx != -1:
            self.emit('pip-start', self._pip_idx, pos)

    def _reset_cam_button(self, idx):
        but = self.builder.get_object('cam%d'%idx)
        if but:
            but.set_active(False)

    def pip_stop_but(self, widget):
        self.emit('pip-off', -1)
        for idx in range(3):
            self._reset_cam_button(idx)

    def on_keypress (self, widget, event):
        key = event.string
        if key:
            self.push_key(key)
        return True

    def clear_buffer(self):
        self.input_buffer.clear()

    def push_key(self, key):
        if key == chr(27):
            self.state = 'switch'
            self.clear_buffer()
            return
        self.input_buffer.append(key)
        next_state = self.states[self.state](key)
        if next_state:
            self.state = next_state

    def switch(self, key):
        values = "1234567890"

        key = key.lower()
        if key in values:
            self.emit('switch', values.index(key))
        elif key in "p":
            return 'pip'

        self.clear_buffer()
        return

    def pip(self, key):
        values = "1234567890"
        actions = "o"

        key = key.lower()
        if key in values:
            return 'pip_sel_cam'
        elif key in actions:
            self.emit('pip-off', -1)

        self.clear_buffer()
        return 'switch'

    def pip_sel_cam(self, key):
        positions = {
            'q': 'TL', 'w': 'TC', 'e': 'TR',
            'a': 'CL', 's': 'CC', 'd': 'CR',
            'z': 'BL', 'x': 'BC', 'c': 'BR',
        }
        actions = "o"

        key = key.lower()
        self.input_buffer.pop()
        idx = int(self.input_buffer.pop()) - 1
        if key in positions:
            self.emit('pip-start', idx, positions[key])
        elif key in actions:
            self._reset_cam_button(idx)
            self.emit('pip-off', idx)

        self.clear_buffer()
        return 'switch'

GObject.type_register(PipManager)


class RecordWidget(Gtk.Box):
    __gsignals__ = {
        # camera idx, -1 for all.
        "record-start":   (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
        "record-stop":    (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
        "select-folder":  (GObject.SIGNAL_RUN_FIRST, None, [GObject.TYPE_PYOBJECT]),
    }
    def __init__(self, *args, **kwargs):
        Gtk.Box.__init__(self)
        builder = Gtk.Builder ()
        self.builder = builder
        self.conf = config.get('FileArchiving', {})

        builder.add_objects_from_file (config.get('rec_ui','rec.ui'), ['RecordWidget'])
        main = builder.get_object('RecordWidget')
        self.add(main)

        self.builder.get_object('rec_start').connect('clicked', self.rec_start)
        self.builder.get_object('rec_stop').connect('clicked', self.rec_stop)

        self.folder = self.builder.get_object('folder')

        dest = self.conf.setdefault('folder', '')
        if not os.path.isdir(dest):
            os.makedirs(dest)
        self.folder.set_filename(dest)

        self.folder.connect('selection-changed', self.folder_sel_cb)

    def folder_sel_cb(self, widget, *args):
        self.conf['folder'] = widget.get_filename()

    def rec_start(self, widget, *args):
        self.emit('record-start', self.folder.get_filename())

    def rec_stop(self, widget, *args):
        self.emit('record-stop', self.folder.get_filename())

GObject.type_register(RecordWidget)

if __name__ == '__main__':
    Gtk.init(sys.argv)
    def cb(widget, arg):
        print widget, arg

    window = Gtk.Window()
    smx = SoundMixWidget()
    smx.connect('set-mix-device', cb)
    smx.connect('set-mix-source', cb)
    window.add(smx)
    window.connect ("destroy", lambda app: Gtk.main_quit())
    window.show_all()
    Gtk.main()

