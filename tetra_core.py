import time
from collections import deque
from itertools import ifilter

import gobject
import gst
import glib
import gtk

gobject.threads_init()
gtk.gdk.threads_init()

INPUT_COUNT = 3
# seconds
WINDOW_LENGTH = 1.5
UPDATE_INTERVAL = .25
MIN_ON_AIR_TIME = 3
# dB
DEFAULT_NOISE_BASELINE = -45
NOISE_THRESHOLD = 6
SPEAK_UP_THRESHOLD = 3

PREVIEW_CAPS = gst.Caps ('video/x-raw-yuv,width=640,height=480,rate=30')
#H264_CAPS = gst.Caps ('video/x-h264,width=1280,heigth=720,framerate=30/1,profile=high')
#H264_CAPS = gst.Caps ('video/x-h264,width=1920,heigth=1080,framerate=30/1,profile=high')
PREVIEW_CAPS = gst.Caps ('video/x-raw-yuv,width=320,height=240,rate=30')
H264_CAPS = gst.Caps ('video/x-h264,width=640,framerate=30/1,profile=high')

AUDIO_CAPS = gst.Caps ('audio/x-raw,format=S16LE,rate=32000,channels=2')
INITIAL_INPUT_PROPS = [
                ('initial-bitrate', 12000000),
                ('average-bitrate', 12000000),
                ('peak-bitrate', 12000000),
# broadcast
                ('usage-type', 2),
]
class TetraApp(gobject.GObject):
    def __init__(self):
        gobject.GObject.__init__(self)
        self.current_input = INPUT_COUNT - 1

        self.noise_baseline = DEFAULT_NOISE_BASELINE
        self.speak_up_threshold = SPEAK_UP_THRESHOLD
        self.min_on_air_time = MIN_ON_AIR_TIME

        self.last_switch_time = time.time()

        self.pipeline = pipeline = gst.Pipeline ('pipeline')

        self.inputsel = gst.element_factory_make ('input-selector', None)
        self.pipeline.add (self.inputsel)
        #self.vsink = gst.element_factory_make ('fakesink', None)
        self.vsink = gst.element_factory_make ('autovideosink', None)
        self.pipeline.add (self.vsink)
        parse = gst.element_factory_make ('h264parse', None)
        parse.set_property ('config-interval', 1)
        dec = gst.element_factory_make ('ffdec_h264', None)
        self.pipeline.add (parse)
        self.pipeline.add (dec)
        self.inputsel.link(parse)
        parse.link(dec)
        dec.link(self.vsink)

        self.preview_sinks = []

##
##        self.vsink = gst.element_factory_make ('tcpserversink', None)
##        self.vsink.set_property('host', '127.0.0.1')
##        self.vsink.set_property('port', 9078)
##        self.vpay = gst.element_factory_make ('mp4mux', None)
##        parser = gst.element_factory_make ('h264parse', None)
##        parser.set_property ('config-interval',2)
##        self.pipeline.add(parser)
##        self.vpay.set_property('streamable', True)
##        self.vpay.set_property('fragment-duration', 100)

#        self.vsink_preview = gst.element_factory_make ('autovideosink', None)
#        self.vmixer = gst.element_factory_make ('videomixer', None)
#        self.vmixerq = gst.element_factory_make ('queue2', 'vmixer Q')

        self.asink = gst.element_factory_make ('autoaudiosink', None)
        #self.asink = gst.element_factory_make ('fakesink', None)


##         self.pipeline.add (self.vpay)
#        self.pipeline.add (self.vsink_preview)
#        self.pipeline.add (self.vmixer)
#        self.pipeline.add (self.vmixerq)

##        self.inputsel.link_filtered (parser, H264_CAPS)
##        parser.link(self.vpay)
##        self.vpay.link (self.vsink)
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
        self.amixer = gst.element_factory_make ('adder', None)
        self.pipeline.add(self.amixer)
        self.pipeline.add(self.asink)
        self.amixer.link(self.asink)

        for idx in range(INPUT_COUNT):
            dev = '/dev/video%d' % idx
            props = [
                ('device', dev),
                ('auto-start', True),
                ('initial-bitrate', 6000000),
                ('average-bitrate', 6000000),
                ('peak-bitrate', 12000000),
                ('iframe-period', 100),
                ('ltr-buffer-size', 100),
# broadcast
                ('usage-type', 2),
            ]
            self.add_video_source('uvch264_src', props)

        for idx in range(INPUT_COUNT):
### XXX: hw:0 interno en pc
            self.add_audio_source('alsasrc', [('device', 'hw:%d,0' % (idx+1))] )
            continue

### XXX: mejor nomenclatura
        self.preview_sinks.append (self.vsink)

    def add_audio_source (self, sourcename=None, props=None):
        # 10 samples per second
        self.audio_avg.append (deque (maxlen=WINDOW_LENGTH * 10))
        self.audio_peak.append (deque (maxlen=WINDOW_LENGTH * 10))

        name = sourcename or 'audiotestsrc'
        src = gst.element_factory_make (name, None)
        q0 = gst.element_factory_make ('queue2', None)
        q1 = gst.element_factory_make ('queue2', None)
        tee = gst.element_factory_make ('tee', None)
        volume = gst.element_factory_make ('volume', None)
#
        fasink = gst.element_factory_make ('fakesink', None)
        fasink.set_property ('sync', True)
#
        aconv = gst.element_factory_make ('audioconvert', None)

        flt = gst.element_factory_make ('audiochebband', None)
        flt.set_property ('lower-frequency', 400)
        flt.set_property ('upper-frequency', 3500)
        level = gst.element_factory_make ('level', None)
        level.set_property ("message", True)

        self.pipeline.add (src)
        self.pipeline.add (q0)
        self.pipeline.add (q1)
        self.pipeline.add (tee)
        self.pipeline.add (volume)
        self.pipeline.add (fasink)
        self.pipeline.add (aconv)
        self.pipeline.add (flt)
        self.pipeline.add (level)

        if props:
            for prop,val in props:
                src.set_property (prop, val)

        caps = gst.Caps ('audio/x-raw-int,rate=32000,channels=2')
        src.link_filtered (q0, caps)
        q0.link (volume)
        volume.link (tee)
        tee.link_filtered(self.amixer, caps)
        tee.link (q1)
        q1.link (aconv)
        aconv.link (flt)
        flt.link (level)
        level.link(fasink)

        self.audio_inputs.append (src)
        self.audio_queues.append (q0)
        self.audio_queues.append (q1)
        self.audio_tees.append (tee)
        self.levels.append (level)
        self.volumes.append (volume)
        self.fasinks.append (fasink)

    def buffer_probe_cb(self, pad, buffer, *args):
        if buffer.flag_is_set(gst.BUFFER_FLAG_DELTA_UNIT):
            print 'KEYFRAME '
        return True
        #print type(arg1), type(arg2), type(args)

    def event_probe_cb(self, pad, event, *args):
        return True

    def add_video_source (self, sourcename=None, props=None):
        name = sourcename or 'v4l2src'
        src = gst.element_factory_make (name, None)
        q0 = gst.element_factory_make ('queue2', None)
        tee = gst.element_factory_make ('tee', None)
        parse = gst.element_factory_make ('h264parse', None)
        dec = gst.element_factory_make ('ffdec_h264', None)
        q1 = gst.element_factory_make ('queue2', None)
        sink = gst.element_factory_make ('autovideosink', None)

        self.pipeline.add (src)
        self.pipeline.add (sink)
        self.pipeline.add (q0)
        self.pipeline.add (q1)
        self.pipeline.add (tee)
        self.pipeline.add (parse)
        self.pipeline.add (dec)

        if props:
            for prop,val in props:
                src.set_property(prop, val)

        src.set_property('message-forward', True)

# XXX:
        q0.set_property ('max-size-time', int(3*gst.SECOND))
        src.link_pads_filtered ('vidsrc', q0, 'sink', H264_CAPS)
        q0.link(tee)
        tee.link(parse)
        tee.link(q1)
        q1.link(self.inputsel)
        parse.link(dec)
        dec.link(sink)

##        src.link_pads_filtered ('vfsrc', q1, 'sink', PREVIEW_CAPS)

##        q0.link (self.inputsel)
##        q1.link (sink)
        self.video_inputs.append(src)
        self.preview_sinks.append (sink)
##        self.video_queues.append(q0)
##        self.video_queues.append(q1)

        vidsrc = src.get_static_pad('vidsrc')
        vidsrc.add_buffer_probe(self.buffer_probe_cb)
        vidsrc.add_event_probe(self.event_probe_cb)

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
        pads = list(isel.sink_pads())
        pads.reverse()
        idx = inputidx % len(pads)

        newpad = pads[idx]
        self.current_input = idx
        if idx != pads.index(oldpad):
            print 'SET ACTIVE INPUT inputidx: ', inputidx, ' idx: ', idx
            isel.set_property('active-pad', newpad)
            s = gst.Structure ('GstForceKeyUnit')
            s.set_value ('running-time', -1)
            s.set_value ('count', 0)
            s.set_value ('all-headers', True)
            ev = gst.event_new_custom (gst.EVENT_CUSTOM_UPSTREAM, s)
            self.video_inputs[idx].send_event (ev)

    def toggle (self, *args):
        e = self.inputsel
        s = e.get_property ('active-pad')
        # pads[0] output, rest input sinks.
        # set_active_input() uses 0..N, so this works out to switch to the next
        i = 1 + list(e.pads()).index(s)
        self.set_active_input(i)

    def start (self):
        self.pipeline.set_state (gst.STATE_PLAYING)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.enable_sync_message_emission()
        bus.connect("message::element", self.bus_element_cb)
        bus.connect("message", self.bus_message_cb)
        bus.connect("sync-message::element", self.bus_sync_message_cb)

        for src in self.video_inputs:
            for prop,val in INITIAL_INPUT_PROPS:
                src.set_property(prop, val)
        self.tid = glib.timeout_add(int (UPDATE_INTERVAL * 1000), self.process_levels)
        glib.timeout_add(int (2 * WINDOW_LENGTH * 1000), self.calibrate_bg_noise)

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
        if msg.structure is None:
            return True
        s = msg.structure
        if s.get_name() == "prepare-xwindow-id":
            for idx,sink in enumerate (self.preview_sinks):
                if msg.src in list(sink.elements()):
                    self.emit ('prepare-xwindow-id', msg.src, idx)
                    print 'app: prepare-xwindow-id for sink: ', idx
            return True

    def bus_element_cb (self, bus, msg, arg=None):
        if msg.structure is None:
            return True

        s = msg.structure
        if s.get_name() == "level":
            idx = self.levels.index (msg.src)
            #print 'RMS ', s['rms']
            rms = sum (s['rms']) / len (s['rms'])
            peak = sum (s['peak']) / len (s['peak'])
            self.audio_avg[idx].append (rms)
            self.audio_peak[idx].append (peak)
            self.emit('level', idx, peak)
        return True

    def bus_message_cb (self, bus, msg, arg=None):
        if msg.type == gst.MESSAGE_CLOCK_LOST:
            self.pipeline.set_state (gst.STATE_PAUSED)
            self.pipeline.set_state (gst.STATE_PLAYING)
        return True


###
gobject.type_register(TetraApp)
# level: chanidx, level
gobject.signal_new("level", TetraApp, gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (int,float))
gobject.signal_new("prepare-xwindow-id", TetraApp, gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_OBJECT,int))
###
