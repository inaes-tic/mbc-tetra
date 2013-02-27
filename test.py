#!/usr/bin/env python

import sys
from gi.repository import GObject
from gi.repository import Clutter
from gi.repository import Gst

GObject.threads_init()
Gst.init(sys.argv)
Clutter.init(sys.argv)

def link (src, pad, dst):
    print src, pad, dst
    if not src.link (dst):
        print (src, pad, dst, "Couldn't link to new pad")

if __name__ == "__main__":
    stage = Clutter.Stage.new ()
    stage.connect("destroy", lambda app: Clutter.main_quit())
    tex = Clutter.Texture.new ()

    stage.add_actor (tex)

    tex.set_keep_aspect_ratio (True)

    sink = Gst.ElementFactory.make ('xvimagesink', None)
#    sink.set_property ('texture', tex)

    pipeline = Gst.Pipeline.new('pipeline')
    src = Gst.ElementFactory.make ('uridecodebin', None)

    print 'uri', sys.argv[1]
    src.set_property ('uri', sys.argv[1])
    pipeline.add (src)
    pipeline.add (sink)

    if not src.link (sink):
        src.connect ('pad-added', link, sink)

    pipeline.set_state (Gst.State.PLAYING)

    Clutter.main()
