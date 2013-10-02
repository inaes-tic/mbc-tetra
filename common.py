#!/usr/bin/env python

import logging
import sys

import gi
gi.require_version('Gst', '1.0')

from gi.repository import Gst

if not Gst.is_initialized():
    Gst.init(sys.argv)


## FIXME: tamano real mas luego.
## VIDEO_CAPS = Gst.Caps.from_string ('image/jpeg,width=800,heigth=448,rate=30,framerate=30/1')

## 16:9 , alcanza para tres camaras en un usb 2.0.
VIDEO_WIDTH = 1024
VIDEO_HEIGHT = 576

VIDEO_WIDTH = 640
VIDEO_HEIGHT = 480

VIDEO_RATE = "24/1"
VIDEO_CAPS = Gst.Caps.from_string ('image/jpeg,width=%d,height=%d,framerate=%s,format=I420' % (VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_RATE))
VIDEO_CAPS_SIZE = Gst.Caps.from_string ('video/x-raw,width=%d,height=%d,framerate=%s,format=I420' % (VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_RATE))

AUDIO_CAPS = Gst.Caps.from_string ('audio/x-raw,rate=44100,channels=2,format=S16LE')


INPUT_COUNT = 0
# seconds
WINDOW_LENGTH = 1.5
UPDATE_INTERVAL = .25
MIN_ON_AIR_TIME = 3
# dB
DEFAULT_NOISE_BASELINE = -45
NOISE_THRESHOLD = 6
SPEAK_UP_THRESHOLD = 3
# everything below this maps to -inf for display purposes
MIN_PEAK = -70

MANUAL=False

XV_SYNC=True
