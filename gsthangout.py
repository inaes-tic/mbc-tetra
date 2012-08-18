#!/usr/bin/env python
# -*- coding: utf-8 -*-

from gi.repository import Gtk
from gi.repository import Gst

p = Gst.Pipeline("hangout")
v4l = Gst.ElementFactory.create("v4l2src")
xvi = Gst.ElementFactory.create("xvimagesink")

p.add(v4l)
p.add(xvi)

p.set_state(Gst.State.PLAYING)

w = Gtk.Window()
w.connect("destroy", lambda w: Gtk.main_quit())
w.show_all()

Gtk.main()
