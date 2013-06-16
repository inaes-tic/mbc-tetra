#!/usr/bin/env python

import sys
import time
import gi
from gi.repository import GObject
gi.require_version('Gst', '1.0')

from gi.repository import Gst
from gi.repository import Gtk
from gi.repository import GLib

GObject.threads_init()
Gst.init(sys.argv)

INPUT_COUNT = 3


class MainWindow(Gtk.Window):
    def __init__(self, app):
        Gtk.Window.__init__(self, title="test tetra 2")
        self.connect('destroy', Gtk.main_quit)

        self.app = app

        box = self.box = Gtk.Box()
        self.add(box)

        self.toggle = Gtk.Button("Rotate input... ")
        box.add(self.toggle)

        sliders = []
        for idx in range(INPUT_COUNT):
            adj = Gtk.Adjustment(1, 0, 1.5, 0.1, 0.25)
            slider = Gtk.VScale()

            slider.set_adjustment(adj)
            slider.set_inverted(True)
            slider.set_digits(1)
            sliders.append(slider)
            box.add(slider)

        bars = []
        for idx in range(INPUT_COUNT):
            bar = Gtk.ProgressBar()
            bar.set_orientation(Gtk.Orientation.VERTICAL)
            bar.set_inverted(True)

            bars.append(bar)
            box.add(bar)

        for idx in range(INPUT_COUNT):
            sliders[idx].connect("value-changed", self.slider_cb, idx)

        self.sliders = sliders
        self.bars = bars

#        self.tid = GLib.timeout_add(100, self.update_levels)

        bus = app.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::element", self.bus_element_cb)

        self.toggle.connect('clicked', self.app.toggle)

    def bus_element_cb (self, bus, msg):
        s = msg.get_structure()
        if s.get_name() != "level":
            return
        idx = self.app.levels.index(msg.src)
        peak = s.get_value('peak')[0]
        self.bars[idx].set_fraction( 1.0 + peak/20.0 )

#    def update_levels(self):
#        return True

    def slider_cb(self, slider, chan):
        self.app.set_channel_volume (chan, slider.get_value())
        self.app.set_active_input(chan)

class App(object):
    def __init__(self):
        self.pipeline = pipeline = Gst.Pipeline.new('pipeline')

        self.inputsel = Gst.ElementFactory.make ('input-selector', None)
        self.vsink = Gst.ElementFactory.make ('autovideosink', None)
        self.vsink_preview = Gst.ElementFactory.make ('autovideosink', None)
        self.vmixer = Gst.ElementFactory.make ('videomixer', None)
        self.vmixerq = Gst.ElementFactory.make ('queue2', 'vmixer Q')
        #self.asink = Gst.ElementFactory.make ('autoaudiosink', None)
        self.asink = Gst.ElementFactory.make ('fakesink', None)


        self.pipeline.add (self.vsink)
        self.pipeline.add (self.vsink_preview)
        self.pipeline.add (self.vmixer)
        self.pipeline.add (self.vmixerq)
        self.pipeline.add (self.inputsel)

        self.inputsel.link (self.vsink)
        self.vmixer.link (self.vmixerq)
        self.vmixerq.link (self.vsink_preview)

#        black = Gst.ElementFactory.make ('videotestsrc', 'black bg')
#        black = Gst.ElementFactory.make ('fakesrc', 'black bg')
#        black.set_property('is-live', True)
#        self.pipeline.add (black)
#### XXX ver de cambiar segun res del preview
#        caps = Gst.Caps.from_string('video/x-raw,format=YUV2,width=%d,height=240' % (320*INPUT_COUNT) )
#        black.link_filtered(self.vmixer, caps)
#        #black.link(self.vmixer)

        self.audio_inputs = []
        self.audio_queues = []
        self.audio_tees = []
        self.fasinks = []

        self.video_inputs = []
# XXX FIXME: ver en add_video_source
        self.video_tees = []
        self.video_queues = []
        self.volumes = []

        self.levels = []
        self.amixer = Gst.ElementFactory.make ('adder', None)

        self.pipeline.add(self.amixer)
        self.pipeline.add(self.asink)

        self.amixer.link(self.asink)

        for idx in range(INPUT_COUNT):
            dev = '/dev/video%d' % idx
            self.add_video_source(props=[('device', dev)])

        for idx in range(INPUT_COUNT):
            self.add_audio_source('autoaudiosrc' )
            continue
            if idx==0:
                self.add_audio_source('alsasrc' )
                continue

            freq = 440*(idx+1)
            self.add_audio_source(props=[('freq', freq), ('is-live', True)])

        for idx,pad in enumerate(self.vmixer.sinkpads):
            pad.set_property('ypos' , 0)
            pad.set_property('xpos' , 320*idx)

    def add_audio_source(self, sourcename=None, props=None):
        name = sourcename or 'audiotestsrc'
        src = Gst.ElementFactory.make (name, None)
        q0 = Gst.ElementFactory.make ('queue2', None)
        tee = Gst.ElementFactory.make ('tee', None)
        volume = Gst.ElementFactory.make ('volume', None)

        fasink = Gst.ElementFactory.make ('fakesink', None)
        fasink.set_property('sync', True)

        level = Gst.ElementFactory.make ('level', None)
        level.set_property ("message", True)

        self.pipeline.add (src)
        self.pipeline.add (q0)
        self.pipeline.add (tee)
        self.pipeline.add (volume)
        self.pipeline.add (fasink)
        self.pipeline.add (level)

        if props:
            for prop,val in props:
                src.set_property(prop, val)

        src.link (volume)
        volume.link (tee)
        tee.link (q0)
        q0.link (self.amixer)
        tee.link (level)
        level.link(fasink)

        self.audio_inputs.append (src)
        self.audio_queues.append (q0)
        self.audio_tees.append (tee)
        self.levels.append (level)
        self.volumes.append (volume)
        self.fasinks.append (fasink)

    def add_video_source(self, sourcename=None, props=None):
        name = sourcename or 'v4l2src'
        src = Gst.ElementFactory.make (name, None)
        q0 = Gst.ElementFactory.make ('queue2', None)
        q1 = Gst.ElementFactory.make ('queue2', None)
        tee = Gst.ElementFactory.make ('tee', None)

        self.pipeline.add (src)
        self.pipeline.add (q0)
        self.pipeline.add (q1)
        self.pipeline.add (tee)

        if props:
            for prop,val in props:
                src.set_property(prop, val)

# XXX: aca usar el pad de preview de uvch264 en lugar de un tee con lo mismo
        src.link(tee)
        tee.link(q0)
        tee.link(q1)
        q0.link(self.inputsel)
        q1.link(self.vmixer)
        self.video_inputs.append(src)
        self.video_queues.append(q0)
        self.video_queues.append(q1)
        self.video_tees.append(tee)

    def set_channel_volume(self, chanidx, volume):
        print 'SET VOL CHAN ', chanidx, ' VOL: ', volume
        if volume > 1.5:
            volume = 1.5
        elif volume < 0:
            volume = 0

        self.volumes[chanidx].set_property('volume', volume)
        try:
            self.volumes[chanidx].set_property('volume', volume)
        except IndexError:
            pass

    def set_active_input(self, inputidx):
        isel = self.inputsel
        oldpad = isel.get_property ('active-pad')
        # pads[0] output, rest input sinks.
        idx = 1 + (inputidx % (len(isel.pads)-1))

        newpad = isel.pads[idx]
        print 'set active input : oldpad ', oldpad, ' newpad ', newpad, ' idx ', idx, ' newidx ', isel.pads.index(oldpad)
        if idx != isel.pads.index(oldpad):
            isel.set_property('active-pad', newpad)

    def toggle (self, *args):
        e = self.inputsel
        s = e.get_property ('active-pad')
        # pads[0] output, rest input sinks.
        i = e.pads.index(s)
        self.set_active_input(i)

if __name__ == "__main__":

    app = App()

    app.pipeline.set_state (Gst.State.PLAYING)
    w2 = MainWindow(app)
    w2.show_all()

    Gst.debug_bin_to_dot_file(app.pipeline, Gst.DebugGraphDetails.MEDIA_TYPE | Gst.DebugGraphDetails.NON_DEFAULT_PARAMS , 'debug1')
    Gst.debug_bin_to_dot_file(app.pipeline, Gst.DebugGraphDetails.MEDIA_TYPE | Gst.DebugGraphDetails.NON_DEFAULT_PARAMS | Gst.DebugGraphDetails.CAPS_DETAILS, 'debug1')


    Gtk.main()
    sys.exit(0)

