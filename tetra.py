import sys
from gi.repository import Gtk
from gi.repository import GtkClutter
from gi.repository import Cheese
from gi.repository import Clutter
from gi.repository import Gst
from gi.repository import GObject

import GstActor

GObject.threads_init()
Gst.init(sys.argv)
GtkClutter.init(sys.argv)
Gtk.init(sys.argv)

class Camera(GstActor.Texture):
    def __init__(self, dev):
        GstActor.Texture.__init__ (self, dev.get_name())
        self.dev = dev

class VideoBox():
    def __init__(self):
        self.builder = Gtk.Builder ()
        self.builder.add_from_file ('tetra.ui')

        self.window = self.builder.get_object('window1')
        self.window.connect("destroy", lambda app: Gtk.main_quit())
        self.window.connect("draw", self.win_draw_cb)

	self.paned = self.builder.get_object ('paned1')

        self.hembed = GtkClutter.Embed.new()
        self.hembed.set_use_layout_size (True)

        self.stage = self.hembed.get_stage()
        self.stage.set_user_resizable(True)
        self.hmanager = Clutter.BoxLayout.new()
        self.hmanager.set_homogeneous (True)
        self.hbox = Clutter.Box.new(self.hmanager)
        self.stage.add_actor (self.hbox)

        self.paned.add1 (self.hembed)

        self.active_view = Clutter.Clone()
        avembed = GtkClutter.Embed.new()
        avembed.get_stage().add_actor(self.active_view)
        avembed.set_use_layout_size (True)
        self.paned.add2 (avembed)

        device_monitor=Cheese.CameraDeviceMonitor.new()
        device_monitor.connect("added", self.added)
        device_monitor.coldplug()

        self.window.show_all()

    def set_active (self, actor, event=None):
        self.active_view.set_source (actor)

    def added(self, signal, data):
        uuid=data.get_uuid()
        node=data.get_device_node()
        print "uuid is " +str(uuid)
        print "node is " +str(node)

        camera = Camera(data)
        camera.play()

        self.add_gstactor (camera)
        if (not self.active_view):
            self.set_active (camera.get_texture())

    def add_gstactor (self, gstactor):
        actor = gstactor.get_texture ()
        actor.connect ('button-press-event', self.set_active)

#        actor.add_child (rect)

        progress = Gtk.ProgressBar.new()
        progress.set_orientation (Gtk.Orientation.VERTICAL)
        progress.set_property ('fraction', 0.8)

        pa = GtkClutter.Actor.new()
        pab = pa.get_widget()
        pab.add (progress)
#        actor.add_child (pa)

	self.hbox.add_actor (actor)

    def win_draw_cb (self, w, cr):
        cr.set_source_rgba (1.0, 1.0, 1.0, 0.0)
        cr.paint()

        return True


if __name__ == "__main__":
    app = VideoBox()
    app.add_gstactor (GstActor.Texture (src_name = 'uridecodebin', props = {'uri': 'file:///home/xaiki/RN15.webm'}))

    for i in range(2):
        app.add_gstactor (GstActor.Texture (src_name = 'videotestsrc', props = {'pattern': i}))

    Gtk.main()

