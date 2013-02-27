import sys
from gi.repository import Gtk
from gi.repository import Gst
from gi.repository import GtkClutter
from gi.repository import Clutter
from gi.repository import GObject

import GstActor

GObject.threads_init()
GtkClutter.init(sys.argv)
Gtk.init(sys.argv)
Gst.init(sys.argv)

def gtk_clutter_texture ():
    b = Gtk.Button.new_with_label ("hello")
    a = GtkClutter.Actor.new_with_contents (b)

    return a

def gst_clutter_texture ():
    t = Clutter.Texture.new()

    sink = Gst.ElementFactory.make ('cluttersink', None)
    sink.set_property ('texture', t)

    p = Gst.Pipeline.new('pipeline')
    src = Gst.ElementFactory.make ('videotestsrc', None)
    [p.add (e) for e in [src, sink]]

    if (not src.link (sink)):
        raise IOError ("couldn't link src")

    p.set_state (Gst.State.PLAYING)

    return t

w = Gtk.Window()
w.connect ('destroy', lambda w: Gtk.main_quit())
e = GtkClutter.Embed.new()
w.add (e)
s = e.get_stage ()

s.add_child (gtk_clutter_texture())
s.add_child (gst_clutter_texture())

w.show_all ()
Gtk.main ()
