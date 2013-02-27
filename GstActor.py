import sys
from gi.repository import Clutter
from gi.repository import Gst
from gi.repository import GObject

Gst.init(sys.argv)

class Texture ():
    def __init__(self, name=None, src_name='v4l2src', props=None, level_cb=None):
        if (not name and not src_name):
            raise IOError ("have to define name or src_name")

        self.level_cb = level_cb

        self.name = name or src_name
        self.actor = Clutter.Actor.new ()
        self.video_texture = Clutter.Texture.new()
        self.video_texture.set_size (320, 240)
        self.video_texture.set_keep_aspect_ratio(True)

        self.rect = Clutter.Rectangle.new_with_color (Clutter.Color.new(255, 0, 0, 255))
        self.rect.set_size (10, self.video_texture.get_size()[1])
        self.actor.add_actor (self.rect)
        self.actor.add_actor (self.video_texture)

        self.sink = Gst.ElementFactory.make ('cluttersink', self.name + '_sink')
        self.sink.set_property ('texture', self.video_texture)

        self.pipeline = Gst.Pipeline.new(self.name + '_pipeline')
#        capsfilter = Gst.ElementFactory.make ('capsfilter', None)


        self.tee   = Gst.ElementFactory.make ('tee',    self.name + '_tee')
        self.src   = Gst.ElementFactory.make (src_name, self.name + '_src')
        if props:
            print 'setting props:', props
            [self.src.set_property (x, props[x]) for x in props.keys()]

        self.level = Gst.ElementFactory.make ('level', self.name + '_level')
        self.level.set_property ('message', True)
        self.audioconvert = Gst.ElementFactory.make ('audioconvert',
                                                     self.name + '_audioconvert')

        for e in [self.src, self.tee, self.sink, self.audioconvert, self.level]:
            self.pipeline.add (e)


        if not self.src.link   (self.tee):
            self.src.connect ('pad-added', self.link, self.tee)
        if not self.tee.link (self.sink) :
            raise IOError ("couldn't link tee")

        caps = Gst.Caps.from_string ('audio/x-raw')
        if not self.audioconvert.link_filtered (self.level, caps) :
            raise IOError ("couldn't link audioconvert")

        self.bus = self.pipeline.get_bus ();
        self.watch_id = self.bus.add_watch (1, self.message_handler, None);

        self.play()

    def update_rect (self, level):
        self.rect.set_size (10, self.video_texture.get_size()[1]*level[0])

    def set_level_cb (self, cb):
        self.level_cb = cb

    def message_handler (self, bus, msg, arg=None):
        if msg.type == Gst.MessageType.ELEMENT:
            s = msg.get_structure()
            if s.get_name() == "level":
                self.update_rect ([pow (10, v/20) for v in s.get_value ("rms")])
        return True

    def link (self, src, pad, dst):
        print 'got new pad:', pad

        if not src.link(dst):
            if not src.link (self.audioconvert):
                print 'could not link to audio'

    def get_texture (self):
        return self.actor

    def play (self):
        self.pipeline.set_state (Gst.State.PLAYING)

    def pause (self):
        self.pipeline.set_state (Gst.State.PAUSED)

if __name__ == '__main__':
    GObject.threads_init()
    Clutter.init(sys.argv)

    stage = Clutter.Stage.new ()
    stage.connect ('destroy', lambda w: Clutter.main_quit())

    for i in range(2):
        stage.add_actor (Texture (src_name = 'videotestsrc', props = {'pattern': i}).get_texture())

    stage.show()
    Clutter.main()
