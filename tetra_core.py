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

from input_sources import C920Input

INPUT_COUNT = 2
# seconds
WINDOW_LENGTH = 1.5
UPDATE_INTERVAL = .25
MIN_ON_AIR_TIME = 3
# dB
DEFAULT_NOISE_BASELINE = -45
NOISE_THRESHOLD = 6
SPEAK_UP_THRESHOLD = 3

MANUAL=False

XV_SYNC=False
dump_idx = 0



class TetraApp(GObject.GObject):
    __gsignals__ = {
        "level": (GObject.SIGNAL_RUN_FIRST, None, (int,float)),
       "prepare-xwindow-id": (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_OBJECT,int)),
       "prepare-window-handle": (GObject.SIGNAL_RUN_FIRST, None, (GObject.TYPE_OBJECT,int)),
    }
    def __init__(self):
        GObject.GObject.__init__(self)
        self.current_input = INPUT_COUNT - 1
        self._automatic = True

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

        self.audio_avg = []
        self.audio_peak = []

        self.inputs = []
        self.video_inputs = []
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
            vdev = '/dev/video%d' % idx
            vprops = { 'device': vdev }
            adev = 'hw:%d,0' % (idx+1)
            aprops = {'device': adev}

            inp = C920Input(vprops, aprops)
            inp.connect('removed', self.source_removed_cb)
            self.pipeline.add(inp)
            self.inputs.append(inp)

            inp.link(self.amixer)
            inp.link(self.inputsel)

            self.preview_sinks.append(inp.xvsink)
            self.volumes.append(inp.volume)
            self.levels.append(inp.level)

            self.audio_avg.append (deque (maxlen=WINDOW_LENGTH * 10))
            self.audio_peak.append (deque (maxlen=WINDOW_LENGTH * 10))

### XXX: mejor nomenclatura
        self.preview_sinks.append (self.vsink)

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

    def set_automatic(self, auto=True):
        self._automatic = auto

    def set_active_input(self, inputidx):
        isel = self.inputsel
        oldpad = isel.get_property ('active-pad')
        if oldpad is None:
            return
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
        for src in self.inputs:
            src.set_uvc_controls()

    def start (self):
        self.set_uvc_controls()
        self.pipeline.set_state (Gst.State.PLAYING)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::element", self.bus_element_cb)
        bus.connect("message", self.bus_message_cb)
        bus.enable_sync_message_emission()
        bus.connect("sync-message::element", self.bus_sync_message_cb)

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
        if not self._automatic:
            return True

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
            if len(q) == 0:
                print 'empty level queue idx= ', idx
                return True
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

    def source_removed_cb (self, source):
        print 'SOURCE REMOVED CB'
        self.pipeline.set_state (Gst.State.PLAYING)
        for sink in self.preview_sinks:
            sink.set_property('sync', XV_SYNC)
        Gst.debug_bin_to_dot_file(self.pipeline, Gst.DebugGraphDetails.NON_DEFAULT_PARAMS | Gst.DebugGraphDetails.MEDIA_TYPE , 'debug_core_source_removed')


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
        elif msg.type == Gst.MessageType.ERROR:
            #print 'Gst msg ERORR src: %s msg: %s' % (str(msg.src), msg.parse_error())
            try:
                msg.src.get_parent().disconnect_source()
            except AttributeError:
                print 'Gst msg ERORR src: %s msg: %s' % (str(msg.src), msg.parse_error())
                pass

        return True

