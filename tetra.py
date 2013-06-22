#!/usr/bin/env python

import sys
import time
from collections import deque
from itertools import ifilter

import gi
from gi.repository import GObject
gi.require_version('Gst', '0.10')

from gi.repository import Gst
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GLib

GObject.threads_init()
Gdk.threads_init()
Gst.init(sys.argv)

INPUT_COUNT = 3
# seconds
WINDOW_LENGTH = 1.5
UPDATE_INTERVAL = .25
MIN_ON_AIR_TIME = 3
# dB
NOISE_BASELINE = -45
SPEAK_UP_THRESHOLD = 3

#PREVIEW_CAPS = Gst.Caps.from_string ('video/x-raw-yuv,width=640,height=480,rate=30')
#H264_CAPS = Gst.Caps.from_string ('video/x-h264,width=1280,heigth=720,framerate=30/1,profile=high')
##H264_CAPS = Gst.Caps.from_string ('video/x-h264,width=1920,heigth=1080,framerate=30/1,profile=high')

PREVIEW_CAPS = Gst.Caps.from_string ('image/jpeg,width=640,height=480,rate=30')
H264_CAPS = Gst.Caps.from_string ('video/x-h264,width=1024,heigth=576,framerate=30/1,profile=high')

AUDIO_CAPS = Gst.Caps.from_string ('audio/x-raw,format=S16LE,rate=32000,channels=2')

INITIAL_INPUT_PROPS = [
                ('initial-bitrate', 12000000),
                ('average-bitrate', 12000000),
                ('peak-bitrate', 12000000),
# broadcast
                ('usage-type', 2),
]

class MainWindow(Gtk.Window):
    def __init__(self, app):
        Gtk.Window.__init__(self, title="Tetra")
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


        self.toggle.connect('clicked', self.app.toggle)

        app.connect('level', self.update_levels)

    def update_levels (self, app, idx, peak):
        Gdk.threads_enter ()
        frac = 1.0 - peak/NOISE_BASELINE
        if frac < 0:
            frac = 0
        self.bars[idx].set_fraction (frac)
        Gdk.threads_leave ()
        return True

    def slider_cb(self, slider, chan):
        self.app.set_channel_volume (chan, slider.get_value())

class App(GObject.GObject):
    __gsignals__ = {
# level: chanidx, level
        "level": (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (int,float)),
    }
    def __init__(self):
        GObject.GObject.__init__(self)
        self.current_input = 0
        self.last_switch_time = time.time()

        self.pipeline = pipeline = Gst.Pipeline.new ('pipeline')

        self.inputsel = Gst.ElementFactory.make ('input-selector', None)
        #self.vsink = Gst.ElementFactory.make ('autovideosink', None)

        self.vsink = Gst.ElementFactory.make ('tcpserversink', None)
        self.vsink.set_property('host', '127.0.0.1')
        self.vsink.set_property('port', 9078)
        self.vpay = Gst.ElementFactory.make ('mp4mux', None)
        parser = Gst.ElementFactory.make ('h264parse', None)
        parser.set_property ('config-interval',2)
        self.pipeline.add(parser)
        self.vpay.set_property('streamable', True)
        self.vpay.set_property('fragment-duration', 100)

#        self.vsink_preview = Gst.ElementFactory.make ('autovideosink', None)
#        self.vmixer = Gst.ElementFactory.make ('videomixer', None)
#        self.vmixerq = Gst.ElementFactory.make ('queue2', 'vmixer Q')

        self.asink = Gst.ElementFactory.make ('autoaudiosink', None)
        #self.asink = Gst.ElementFactory.make ('fakesink', None)


        self.pipeline.add (self.vsink)
        self.pipeline.add (self.vpay)
#        self.pipeline.add (self.vsink_preview)
#        self.pipeline.add (self.vmixer)
#        self.pipeline.add (self.vmixerq)
        self.pipeline.add (self.inputsel)

        self.inputsel.link_filtered (parser, H264_CAPS)
        parser.set ('config-interval', 1)
        parser.link(self.vpay)
        self.vpay.link (self.vsink)
#        self.vmixer.link (self.vmixerq)
#        self.vmixerq.link (self.vsink_preview)


        self.audio_inputs = []
        self.audio_queues = []
        self.audio_tees = []
        self.audio_avg = []
        self.audio_peak = []
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

        self.amixer.link_filtered (self.asink, AUDIO_CAPS)

        for idx in range(INPUT_COUNT):
            dev = '/dev/video%d' % idx
            props = [
                ('device', dev),
                ('initial-bitrate', 6000000),
                ('average-bitrate', 6000000),
                ('peak-bitrate', 12000000),
# broadcast
                ('usage-type', 2),
            ]
            #self.add_video_source('uvch264_src', props)
            #self.add_video_source('fakesrc', None)
            self.add_video_source('v4l2src', [('device', dev)])

        for idx in range(INPUT_COUNT):
### XXX: hw:0 interno en pc, no asi en bbb.
            self.add_audio_source('alsasrc', [('device', 'hw:%d,0' % (idx+1))] )
            continue

#        for idx,pad in enumerate(self.vmixer.sinkpads):
#            pad.set_property('ypos' , 0)
#            pad.set_property('xpos' , 320*idx)

    def add_audio_source (self, sourcename=None, props=None):
        # 10 samples per second
        self.audio_avg.append (deque (maxlen=WINDOW_LENGTH * 10))
        self.audio_peak.append (deque (maxlen=WINDOW_LENGTH * 10))

        name = sourcename or 'audiotestsrc'
        src = Gst.ElementFactory.make (name, None)
        q0 = Gst.ElementFactory.make ('queue2', None)
        tee = Gst.ElementFactory.make ('tee', None)
        volume = Gst.ElementFactory.make ('volume', None)
#
#
        level = Gst.ElementFactory.make ('level', None)
        level.set_property ("message", True)

        self.pipeline.add (src)
        self.pipeline.add (q0)
        self.pipeline.add (tee)
        self.pipeline.add (volume)
        self.pipeline.add (level)

        if props:
            for prop,val in props:
                src.set_property (prop, val)

        caps = AUDIO_CAPS
        src.link (q0)
        q0.link_filtered (volume, caps)
        volume.link (tee)
        tee.link_filtered (self.amixer, caps)
        tee.link (level)

        self.audio_inputs.append (src)
        self.audio_queues.append (q0)
        self.audio_tees.append (tee)
        self.levels.append (level)
        self.volumes.append (volume)

    def add_video_source (self, sourcename=None, props=None):
        name = sourcename or 'v4l2src'
        src = Gst.ElementFactory.make (name, None)
        q0 = Gst.ElementFactory.make ('queue2', None)
        #q1 = Gst.ElementFactory.make ('queue2', None)

        self.pipeline.add (src)
        self.pipeline.add (q0)
        #self.pipeline.add (q1)

        if props:
            for prop,val in props:
                src.set_property(prop, val)

# XXX:
        #src.link_pads_filtered ('vidsrc', q0, 'sink', H264_CAPS)
        src.link_filtered (q0, H264_CAPS)

        #src.link_pads_filtered ('vfsrc', q1, 'sink', PREVIEW_CAPS)

        q0.link (self.inputsel)
        #q1.link (self.vmixer)
        self.video_inputs.append(src)
        self.video_queues.append(q0)
        #self.video_queues.append(q1)

    def set_channel_volume(self, chanidx, volume):
        if volume > 1.5:
            volume = 1.5
        elif volume < 0:
            volume = 0

        try:
            self.volumes[chanidx].set_property('volume', volume)
        except IndexError:
            pass

    def set_active_input(self, inputidx):
        isel = self.inputsel
        oldpad = isel.get_property ('active-pad')
        pads = isel.sinkpads
        idx = inputidx % len(pads)

        newpad = pads[idx]
        self.current_input = inputidx
        if idx != pads.index(oldpad):
            isel.set_property('active-pad', newpad)
            s = gst.Structure ('GstForceKeyUnit')
            s.set_value ('running-time', gst.CLOCK_TIME_NONE)
            s.set_value ('count', 0)
            s.set_value ('all-headers', True)
            ev = gst.event_new_custom (gst.EVENT_CUSTOM_UPSTREAM, s)
            self.video_inputs.send_event (ev)

    def toggle (self, *args):
        e = self.inputsel
        s = e.get_property ('active-pad')
        # pads[0] output, rest input sinks.
        # set_active_input() uses 0..N, so this works out to switch to the next
        i = e.pads.index(s)
        self.set_active_input(i)

    def start (self):
        bus = self.pipeline.get_bus ()
        self.watch_id = bus.add_watch_full (GLib.PRIORITY_DEFAULT, self.bus_message_cb, None);

        #bus.add_signal_watch ()
        #bus.connect("message", self.bus_message_cb)
        self.pipeline.set_state (Gst.State.PLAYING)

## XXX: solo para uvch264
##        for src in self.video_inputs:
##            src.emit('start-capture')
##            for prop,val in INITIAL_INPUT_PROPS:
##                src.set_property(prop, val)

        self.tid = GLib.timeout_add(int (UPDATE_INTERVAL * 1000), self.process_levels)

# XXX: devolver True, sino el timeout se destruye
    def process_levels (self):
        now = time.time()
        def do_switch (src):
            if src == self.current_input:
                return
            self.last_switch_time = now
            self.set_active_input (src)
            print 'DO_SWITCH ', src

        if (now - self.last_switch_time) < MIN_ON_AIR_TIME:
            return True
        print 'PROCESS current_input ', self.current_input
        dpeaks = []
        avgs = []
        for idx,q in enumerate (self.audio_avg):
            avgs.append ( (idx, sum (q) / (10*WINDOW_LENGTH)) )

        for idx,q in enumerate (self.audio_avg):
            dp = []
            for (x1,x2) in zip (q, list(q)[1:]):
                dp.append (x2-x1)
            dpeaks.append ( (idx, sum(dp) / (10*(WINDOW_LENGTH-1))) )

# ver caso si mas de uno pasa umbral.
        peaks_over = filter (lambda x: x[1] > SPEAK_UP_THRESHOLD, dpeaks)
        if peaks_over:
            idx, peak = max (peaks_over, key= lambda x: x[1])
            print ' PEAKS OVER ', peaks_over
            do_switch (idx)
            return True

        idx, avg = max (avgs, key= lambda x: x[1])
        do_switch (idx)
        #return True

        print ' AVGs ', avgs , ' dPEAKs ', dpeaks
        return True


    def message_level_cb (self, bus, msg, arg=None):
        idx = self.levels.index (msg.src)
        s = msg.get_structure()
        self.audio_avg[idx].append (s.get_value('rms')[0])
        self.audio_peak[idx].append (s.get_value('peak')[0])
        self.emit('level', idx, s.get_value('peak')[0])
        return True

    def bus_message_cb (self, bus, msg, arg=None):
        if msg.type == Gst.MessageType.CLOCK_LOST:
            self.pipeline.set_state (Gst.State.PAUSED)
            self.pipeline.set_state (Gst.State.PLAYING)

        elif msg.type == Gst.MessageType.ELEMENT:
            if msg.get_structure() and msg.get_structure().get_name() == 'level':
                self.message_level_cb (bus, msg, arg)

        return True


#        if msg.src not in self.video_inputs:
#            return
##         if msg.type == gst.MESSAGE_ERROR:
##             self.pipeline.set_state (gst.STATE_PAUSED)
##             for src in self.video_inputs:
##                 src.set_state (gst.STATE_NULL)
##                 for q in self.video_queues:
##                     src.unlink(q)
##                 self.pipeline.remove (src)
            #self.pipeline.set_state (gst.STATE_NULL)
            #self.pipeline.set_state (gst.STATE_PLAYING)




if __name__ == "__main__":

    app = App()

    w2 = MainWindow(app)
    w2.show_all()

    app.start()

    #Gst.debug_bin_to_dot_file(app.pipeline, Gst.DebugGraphDetails.MEDIA_TYPE | Gst.DebugGraphDetails.NON_DEFAULT_PARAMS | Gst.DebugGraphDetails.CAPS_DETAILS, 'debug1')

    Gtk.main()
    sys.exit(0)

