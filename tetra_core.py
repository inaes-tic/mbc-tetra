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
from gi.repository import GLib

GObject.threads_init()
Gst.init(sys.argv)

INPUT_COUNT = 3
# seconds
WINDOW_LENGTH = 1.5
UPDATE_INTERVAL = .25
MIN_ON_AIR_TIME = 3
# dB
DEFAULT_NOISE_BASELINE = -45
NOISE_THRESHOLD = 6
SPEAK_UP_THRESHOLD = 3

## FIXME: tamano real mas luego.
## VIDEO_CAPS = Gst.Caps.from_string ('image/jpeg,width=320,rate=30,framerate=30/1')
## VIDEO_CAPS = Gst.Caps.from_string ('image/jpeg,width=1024,rate=30,framerate=30/1')
VIDEO_CAPS = Gst.Caps.from_string ('image/jpeg,width=800,heigth=448,rate=30,framerate=30/1')
AUDIO_CAPS = Gst.Caps.from_string ('audio/x-raw,format=S16LE,rate=32000,channels=2')

XV_SYNC=False
MANUAL=False

class TetraApp(GObject.GObject):
    __gsignals__ = {
        "level": (GObject.SIGNAL_RUN_FIRST, None, (int,float)),
       "prepare-xwindow-id": (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_OBJECT,int)),
       "prepare-window-handle": (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_OBJECT,int)),
    }
    def __init__(self):
        GObject.GObject.__init__(self)
        self.current_input = INPUT_COUNT - 1

        self.noise_baseline = DEFAULT_NOISE_BASELINE
        self.speak_up_threshold = SPEAK_UP_THRESHOLD
        self.min_on_air_time = MIN_ON_AIR_TIME

        self.last_switch_time = time.time()

        self.pipeline = pipeline = Gst.Pipeline.new ('pipeline')

        self.inputsel = Gst.ElementFactory.make ('input-selector', None)
        self.pipeline.add (self.inputsel)
        #self.vsink = Gst.ElementFactory.make ('fakesink', None)
        q = Gst.ElementFactory.make ('queue2', None)
        self.vsink = Gst.ElementFactory.make ('xvimagesink', None)
        self.vsink.set_property('sync', XV_SYNC)
        self.pipeline.add (q)
        self.pipeline.add (self.vsink)
        self.inputsel.link(q)
        q.link(self.vsink)
        self.preview_sinks = []

        self.asink = Gst.ElementFactory.make ('autoaudiosink', None)

        self.audio_inputs = []
        self.audio_queues = []
        self.audio_tees = []
        self.audio_avg = []
        self.audio_peak = []
        self.fasinks = []

        self.video_inputs = []
        self.video_tees = []
        self.video_queues = []
        self.volumes = []

        self.levels = []
        self.amixer = Gst.ElementFactory.make ('adder', None)

        q = Gst.ElementFactory.make ('queue2', None)
        self.pipeline.add(q)
        self.pipeline.add(self.amixer)
        self.pipeline.add(self.asink)
        self.amixer.link(q)
        q.link(self.asink)

        for idx in range(INPUT_COUNT):
            dev = '/dev/video%d' % idx
            props = {
                'device': dev,
            }
            self.add_video_source('v4l2src', props)

        for idx in range(INPUT_COUNT):
### XXX: hw:0 interno en pc
### XXX: poner regla fija en udev.
            self.add_audio_source('alsasrc', {'device': 'hw:%d,0' % (idx+1)} )
            continue

### XXX: mejor nomenclatura
        self.preview_sinks.append (self.vsink)

    def add_audio_source (self, sourcename=None, props=None):
        # 10 samples per second
        self.audio_avg.append (deque (maxlen=WINDOW_LENGTH * 10))
        self.audio_peak.append (deque (maxlen=WINDOW_LENGTH * 10))

        name = sourcename or 'audiotestsrc'
        src = Gst.ElementFactory.make (name, None)
        q0 = Gst.ElementFactory.make ('queue2', None)
        q1 = Gst.ElementFactory.make ('queue2', None)
        q2 = Gst.ElementFactory.make ('queue2', None)
        tee = Gst.ElementFactory.make ('tee', None)
        volume = Gst.ElementFactory.make ('volume', None)
#
        fasink = Gst.ElementFactory.make ('fakesink', None)
        fasink.set_property ('sync', False)
#
        aconv = Gst.ElementFactory.make ('audioconvert', None)

        flt = Gst.ElementFactory.make ('audiochebband', None)
        flt.set_property ('lower-frequency', 400)
        flt.set_property ('upper-frequency', 3500)
        level = Gst.ElementFactory.make ('level', None)
        level.set_property ("message", True)

        self.pipeline.add (src)
        self.pipeline.add (q0)
        self.pipeline.add (q1)
        self.pipeline.add (q2)
        self.pipeline.add (tee)
        self.pipeline.add (volume)
        self.pipeline.add (fasink)
        self.pipeline.add (aconv)
        self.pipeline.add (flt)
        self.pipeline.add (level)

        if props:
            for prop,val in props.items():
                src.set_property (prop, val)

        caps = AUDIO_CAPS
        src.link_filtered (q0, caps)
        q0.link (volume)
        volume.link (tee)
        tee.link (q1)
        tee.link (q2)
        q1.link (aconv)
        q2.link_filtered(self.amixer, caps)
        aconv.link (flt)
        flt.link (level)
        level.link(fasink)

        self.audio_inputs.append (src)
        self.audio_queues.append (q0)
        self.audio_queues.append (q1)
        self.audio_queues.append (q2)
        self.audio_tees.append (tee)
        self.levels.append (level)
        self.volumes.append (volume)
        self.fasinks.append (fasink)

    def add_video_source (self, sourcename=None, props=None):
        name = sourcename or 'v4l2src'
        src = Gst.ElementFactory.make (name, None)
        q0 = Gst.ElementFactory.make ('queue2', None)
        tee = Gst.ElementFactory.make ('tee', None)
        parse = Gst.ElementFactory.make ('jpegparse', None)
        dec = Gst.ElementFactory.make ('jpegdec', None)
        q1 = Gst.ElementFactory.make ('queue2', None)
        q2 = Gst.ElementFactory.make ('queue2', None)
        sink = Gst.ElementFactory.make ('xvimagesink', None)
        sink.set_property('sync', XV_SYNC)

        self.pipeline.add (src)
        self.pipeline.add (sink)
        self.pipeline.add (q0)
        self.pipeline.add (q1)
        self.pipeline.add (q2)
        self.pipeline.add (tee)
        self.pipeline.add (parse)
        self.pipeline.add (dec)

        if props:
            for prop,val in props.items():
                src.set_property(prop, val)

# XXX:
        #q0.set_property ('max-size-time', int(1*Gst.SECOND))
        src.link(q0)
        q0.link_filtered(parse, VIDEO_CAPS)
        #parse.link(tee)
        parse.link(dec)
        dec.link(tee)
        tee.link(q1)
        tee.link(q2)
        q1.link(self.inputsel)
        q2.link(sink)

        self.video_inputs.append(src)
        self.preview_sinks.append (sink)

    def mute_channel (self, chanidx, mute):
        try:
            self.volumes[chanidx].set_property('mute', mute)
        except IndexError:
            pass

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
        self.current_input = idx
        if idx != pads.index(oldpad):
            print 'SET ACTIVE INPUT inputidx: ', inputidx, ' idx: ', idx
            isel.set_property('active-pad', newpad)
##             s = Gst.Structure ('GstForceKeyUnit')
##             s.set_value ('running-time', -1)
##             s.set_value ('count', 0)
##             s.set_value ('all-headers', True)
##             ev = Gst.event_new_custom (Gst.EVENT_CUSTOM_UPSTREAM, s)
##             self.video_inputs[idx].send_event (ev)

    def toggle (self, *args):
        e = self.inputsel
        s = e.get_property ('active-pad')
        # pads[0] output, rest input sinks.
        # set_active_input() uses 0..N, so this works out to switch to the next
        i = e.pads.index(s)
        self.set_active_input(i)

# XXX: 
    def set_uvc_controls (self):
        cmd = "uvcdynctrl -s 'Exposure, Auto Priority' 0 --device="
        for src in self.video_inputs:
            os.system(cmd + src.get_property('device'))

    def start (self):
        self.set_uvc_controls()
        self.pipeline.set_state (Gst.State.PLAYING)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::element", self.bus_element_cb)
        bus.connect("message", self.bus_message_cb)
        bus.enable_sync_message_emission()
        bus.connect("sync-message::element", self.bus_sync_message_cb)

        if not MANUAL:
            self.tid = GLib.timeout_add(int (UPDATE_INTERVAL * 1000), self.process_levels)
        GLib.timeout_add(int (2 * WINDOW_LENGTH * 1000), self.calibrate_bg_noise)

    def calibrate_bg_noise (self, *args):
        res = 0
        for q in self.audio_avg:
            res += sum (q) / (10*WINDOW_LENGTH)
        res /= len (self.audio_avg)
        self.noise_baseline = res
        print 'NOISE BG: ', res

# XXX: devolver True, sino el timeout se destruye
    def process_levels (self):
        now = time.time()
        def do_switch (src):
            if src == self.current_input:
                return
            self.last_switch_time = now
            self.set_active_input (src)
            print 'DO_SWITCH ', src
        def do_rotate():
            self.last_switch_time = now
            self.set_active_input (self.current_input+1)
            print 'DO_ROTATE '

        if (now - self.last_switch_time) < self.min_on_air_time:
            return True
###        print 'PROCESS current_input ', self.current_input

        dpeaks = []
        avgs = []
        silent = True
        for idx,q in enumerate (self.audio_avg):
            avg = sum (q) / (10*WINDOW_LENGTH)
            dp = (q[-1] - q[0])
            avgs.append ( (idx, avg) )
            dpeaks.append ( (idx, dp) )
            if abs (avg-self.noise_baseline) > NOISE_THRESHOLD:
                silent = False
        if silent:
            do_rotate ()
            return True

##        for idx,q in enumerate (self.audio_avg):
##            dp = []
##            for (x1,x2) in zip (q, list(q)[1:]):
##                dp.append (x2-x1)
##            dpeaks.append ( (idx, sum(dp) / (10*(WINDOW_LENGTH-1))) )

# ver caso si mas de uno pasa umbral.
        peaks_over = filter (lambda x: x[1] > self.speak_up_threshold, dpeaks)
        if peaks_over:
            idx, peak = max (peaks_over, key= lambda x: x[1])
            print ' PEAKS OVER ', peaks_over
            if abs(avgs[idx][1] - self.noise_baseline) > NOISE_THRESHOLD:
                do_switch (idx)
                return True

        idx, avg = max (avgs, key= lambda x: x[1])
        do_switch (idx)

###        print ' AVGs ', avgs , ' dPEAKs ', dpeaks
        return True


    def bus_sync_message_cb (self, bus, msg):
        if msg.get_structure() is None:
            return True
        s = msg.get_structure()
        if s.get_name() in  ("prepare-xwindow-id", "prepare-window-handle"):
            idx = self.preview_sinks.index(msg.src)
            self.emit (s.get_name(), msg.src, idx)
            return True

    def bus_element_cb (self, bus, msg, arg=None):
        if msg.get_structure() is None:
            return True

        s = msg.get_structure()
        if s.get_name() == "level":
            idx = self.levels.index (msg.src)
            arms = s.get_value('rms')
            apeak = s.get_value('peak')
            rms = sum (arms) / len (arms)
            peak = sum (apeak) / len (apeak)
            self.audio_avg[idx].append (rms)
            self.audio_peak[idx].append (peak)
            self.emit('level', idx, peak)
        return True

    def bus_message_cb (self, bus, msg, arg=None):
        if msg.type == Gst.MessageType.CLOCK_LOST:
            self.pipeline.set_state (Gst.State.PAUSED)
            self.pipeline.set_state (Gst.State.PLAYING)
        return True

