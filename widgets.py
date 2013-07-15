#!/usr/bin/env python

import logging

import sys
import time

import gi

from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gtk

import config

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

        active_card = self.config.setdefault('extern_card', 'default')

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

