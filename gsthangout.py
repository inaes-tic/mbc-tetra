#!/usr/bin/env python
# -*- coding: utf-8 -*-

from gi.repository import Gtk

from gi.repository import Gst
from gi.repository import Clutter
from gi.repository import GtkClutter
from gi.repository import Cheese
# FIXME: this still requires Gst 0.10, it's the only impediment to migrate to 1.0
from gi.repository import ClutterGst

ClutterGst.init(None)
Gst.init(None)

class CameraHandler:
    def __init__ ():

        self.cameras = {}

        self.mon = Cheese.CameraDeviceMonitor()
        self.mon.connect ('added',   camera_plugged_cb,   self.cameras)
        self.mon.connect ('removed', camera_unplugged_cb, self.cameras)
        self.mon.coldplug()

    def camera_plugged_cb (mon, dev, cameras):
        print "found camera: '%s'" % dev.get_name()
        cameras[dev.get_uuid()] = dev
        camera_to_texture (dev)

    def camera_unplugged_cb (mon, dev, cameras):
        print "removing camera: '%s'" % dev.get_name()
        del (cameras[dev.get_uuid()])

    def camera_to_texture (dev):
        fmt = dev.get_best_format()

        texture = Clutter.Texture()
        cam = Cheese.Camera.new(texture,
                            dev.get_device_node (),
                            fmt.width/4, fmt.height/4)
        texture.set_size (fmt.width/4, fmt.height/4)
        print "got camera: %s, texture: %s, %s" % (cam, texture, fmt)

        cam.setup (dev.get_uuid())
        cam.play()

        return texture

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

w.connect("destroy", lambda w: Clutter.main_quit())
w.show_all()

#xvi.set_parent(da.get_window())

Clutter.main()
