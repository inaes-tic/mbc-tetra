#!/usr/bin/env python

import sys
import gi
from gi.repository import GObject
gi.require_version('Gst', '1.0')

from gi.repository import Gst
from gi.repository import Gtk

GObject.threads_init()
Gst.init(sys.argv)

INPUT_COUNT = 1

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
    sink = Gst.ElementFactory.make ('autovideosink', None)

    pipeline.add (sink)
    pipeline.add (inputsel)

    inputsel.link (sink)

    inputs = []
    queues = []
    #caps = Gst.Caps.from_string('image/jpeg, width=(int)640, height=(int)480')
    caps = Gst.Caps.from_string('video/x-raw, width=(int)640, height=(int)480')
    for i in range(INPUT_COUNT):
        inputs.append(Gst.ElementFactory.make ('v4l2src', None))
        queues.append(Gst.ElementFactory.make ('queue2', None))

        pipeline.add (inputs[i])
        pipeline.add (queues[i])
        inputs[i].set_property('device', '/dev/video0')
        inputs[i].link_filtered (queues[i], caps)
        #inputs[i].link(queues[i])
        queues[i].link (inputsel)

    i = 1
    inputs.append(Gst.ElementFactory.make ('videotestsrc', None))
    queues.append(Gst.ElementFactory.make ('queue2', None))

    pipeline.add (inputs[i])
    pipeline.add (queues[i])
    inputs[i].link_filtered (queues[i], caps)
    #inputs[i].link(queues[i])
    queues[i].link (inputsel)


    pipeline.set_state (Gst.State.PLAYING)

    w = Gtk.Window(Gtk.WindowType.TOPLEVEL)
    b = Gtk.Button("click me")
    w.add(b)
    w.show_all()

    b.connect ('clicked', toggle, inputsel)
    w.connect ('destroy', lambda (w): Gtk.main_quit())

    Gtk.main()

