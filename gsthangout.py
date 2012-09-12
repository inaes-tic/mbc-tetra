#!/usr/bin/env python
# -*- coding: utf-8 -*-

from gi.repository import Gtk

from gi.repository import Gst
from gi.repository import Clutter
from gi.repository import GtkClutter
# FIXME: this still requires Gst 0.10, it's the only impediment to migrate to 1.0
from gi.repository import ClutterGst

ClutterGst.init(None)
Gst.init(None)

def sync_cb (bus, msg, o):
    print bus, msg, o


    del msg
    return Gst.BusSyncReply.PASS

p = Gst.Pipeline()
#bus = p.get_bus()
#bus.set_sync_handler (sync_cb, None)

print "init2"

v4l = Gst.ElementFactory.make("v4l2src", "v4l")
xvi = Gst.ElementFactory.make("autovideosink", "xvi")
tst = Gst.ElementFactory.make("videotestsrc", "test")
print "init"

tex = Clutter.Texture()
clv = Gst.ElementFactory.make("cluttersink", "clutter")
clv.props.texture = tex

print p, v4l, clv

p.add(tst)
p.add(clv)

p.set_state(Gst.State.PLAYING)

def win_draw_cb (w, cr):
    cr.set_source_rgba (1.0, 1.0, 1.0, 0.0)
    cr.set_operator (cairo.OPERATOR_SOURCE)
    cr.paint()

    return True

w = Gtk.Window()
w.set_app_paintable (True)
w.connect("draw", win_draw_cb)
e = GtkClutter.Embed()
w.add(e)
s = e.get_stage()
s.set_user_resizable(True)

c = Clutter.Color()
c.from_string ("#0000")
s.set_color (c)

s.add_actor(tex)
s.show_all()

w.connect("destroy", lambda w: Gtk.main_quit())
w.show_all()

#xvi.set_parent(da.get_window())

Clutter.main()
