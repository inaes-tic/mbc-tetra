#!/usr/bin/env python

import sys
import gi
from gi.repository import GObject
gi.require_version('Gst', '1.0')

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

class MainWindow(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="test tetra 2")
        box = self.box = Gtk.Box()
        self.add(box)

        self.toggle = Gtk.Button("Rotate input... ")
        box.add(self.toggle)

#        hbox = Gtk.Box()
#        hbox.set_property("orientation", Gtk.Orientation.VERTICAL)
#        box.add(hbox)

        sliders = []
        for idx in range(3):
            adj = Gtk.Adjustment(1, 0, 1.5, 0.1, 0.25)
            slider = Gtk.VScale()

            slider.set_adjustment(adj)
            slider.set_inverted(True)
            slider.set_digits(1)
            sliders.append(slider)
            box.add(slider)

        bars = []
        for idx in range(3):
            bar = Gtk.ProgressBar()
            bar.set_orientation(Gtk.Orientation.VERTICAL)
            bar.set_inverted(True)

            bars.append(bar)
            box.add(bar)

        for idx in range(3):
            sliders[idx].connect("value-changed", self.slider_cb, bars[idx])

        self.sliders = sliders
        self.bars = bars

    def slider_cb(self, slider, data):
        data.set_fraction (slider.get_value() / 1.5)


if __name__ == "__main__":

    pipeline = Gst.Pipeline.new('pipeline')

    inputsel = Gst.ElementFactory.make ('input-selector', None)
    sink = Gst.ElementFactory.make ('autovideosink', None)
    #asink = Gst.ElementFactory.make ('autoaudiosink', None)

    pipeline.add (sink)
    pipeline.add (inputsel)

    inputsel.link (sink)

    audio_inputs = []
    audio_queues = []
    volumes = []
    #levels = Gst.ElementFactory.make ('level', 'levels')
    #amixer = Gst.ElementFactory.make ('adder', None)

    #pipeline.add(amixer)
    #pipeline.add(final_level)
    #pipeline.add(asink)
    #amixer.link (final_level)
    #final_level.link (asink)

    inputs = []
    queues = []
    #caps = Gst.Caps.from_string('image/jpeg, width=(int)640, height=(int)480')
    caps = Gst.Caps.from_string('video/x-raw, width=(int)640, height=(int)480')
    for i in range(INPUT_COUNT):
        # XXX audio_inputs.append(Gst.ElementFactory.make ('autoaudiosrc', None))
    #    audio_inputs.append(Gst.ElementFactory.make ('audiotestsrc', None))
    #    audio_queues.append(Gst.ElementFactory.make ('queue2', None))
    #    audio_inputs[i].set_property("freq", 440*(i+1))
    #    levels.append(Gst.ElementFactory.make ('level', 'level%d'%i))

    #    pipeline.add (audio_inputs[i])
    #    pipeline.add (audio_queues[i])
    #    pipeline.add (levels[i])

    #    audio_inputs[i].link (audio_queues[i])
    #    audio_queues[i].link (levels[i])
    #    levels[i].set_property ("message", True)
    #    levels[i].link (amixer)

        inputs.append(Gst.ElementFactory.make ('v4l2src', None))
        queues.append(Gst.ElementFactory.make ('queue2', None))

        pipeline.add (inputs[i])
        pipeline.add (queues[i])
        inputs[i].set_property('device', '/dev/video%d'%i)
        #inputs[i].link_filtered (queues[i], caps)
        inputs[i].link(queues[i])
        queues[i].link (inputsel)

    pipeline.set_state (Gst.State.PLAYING)

    w = Gtk.Window(Gtk.WindowType.TOPLEVEL)
    b = Gtk.Button("click me")
    w.add(b)
    w.show_all()

    b.connect ('clicked', toggle, inputsel)
    w.connect ('destroy', lambda (w): Gtk.main_quit())


    w2 = MainWindow()
    bus = pipeline.get_bus()

    def cb_elm(bus, msg, data):
        s = msg.get_structure()
        if s.get_name() != "level":
            return
        print s.get_value('peak')
        #print s.get_name_id(), s.name,  s.get_name(), s.to_string()

        return
        idx = levels.index(s)
        print 'IDX: ', idx, ' PEAK: ', s.get_value("peak")[0]
        arg.bars[idx].set_fraction(s.get_value("peak")[0])
        #print bus, msg, data

    def message_handler (bus, msg, arg=None):
        #print msg, arg
        s = msg.get_structure()
        if s.get_name() != "level":
            return

        idx = levels.index(s)
        print 'IDX: ', idx, ' PEAK: ', s.get_value("peak")[0]
        arg.bars[idx].set_fraction(s.get_value("peak")[0])
#            if s.get_name() == "level"
#                self.update_rect ([pow (10, v/20) for v in s.get_value ("rms")])
        return True

    def cb2(a=None, b=None, c=None):
        print a,b,c

    bus.add_signal_watch()

    bus.connect("message::element", cb_elm, w2)
    #watch_id = bus.add_watch (1, message_handler, None);

    Gst.debug_bin_to_dot_file(pipeline, Gst.DebugGraphDetails.MEDIA_TYPE | Gst.DebugGraphDetails.NON_DEFAULT_PARAMS, 'debug1')
    w2.show_all()
    Gtk.main()

