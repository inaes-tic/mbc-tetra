#!/usr/bin/env python

import sys
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import Gtk

GObject.threads_init()
Gst.init(sys.argv)

INPUT_COUNT = 3

def toggle (button, e):
    s = e.get_property ('active-pad')
    i = (e.pads.index(s) + 1) % e.pads.__len__()
    if (i == 0):
        i = 1
    e.set_property('active-pad', e.pads[i])

if __name__ == "__main__":
    sink = Gst.ElementFactory.make ('xvimagesink', None)
#    sink.set_property ('texture', tex)

    pipeline = Gst.Pipeline.new('pipeline')

    inputsel = Gst.ElementFactory.make ('input-selector', None)
    sink = Gst.ElementFactory.make ('xvimagesink', None)

    pipeline.add (sink)
    pipeline.add (inputsel)

    inputsel.link (sink)

    inputs = []
    queues = []
    for i in range(INPUT_COUNT):
        inputs.append(Gst.ElementFactory.make ('videotestsrc', None))
        queues.append(Gst.ElementFactory.make ('queue2', None))

        pipeline.add (inputs[i])
        pipeline.add (queues[i])
        inputs[i].set_property('pattern', i)
        inputs[i].link (queues[i])
        queues[i].link (inputsel)

    pipeline.set_state (Gst.State.PLAYING)

    w = Gtk.Window(Gtk.WindowType.TOPLEVEL)
    b = Gtk.Button("click me")
    w.add(b)
    w.show_all()

    b.connect ('clicked', toggle, inputsel)
    w.connect ('destroy', lambda (w): Gtk.main_quit())

    Gtk.main()

