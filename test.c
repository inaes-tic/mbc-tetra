#include <glib/gprintf.h>
#include <clutter-gst/clutter-gst.h>
#include <gst/gst.h>


static void
cb_new_pad (GstElement *element,
	    GstPad     *pad,
	    gpointer    data)
{
  gchar *name;
  GstElement *dst = data;

  name = gst_pad_get_name (pad);
  g_print ("A new pad %s was created\n", name);
  g_free (name);

  gst_element_link (element, dst);
}

int
main (int argc, char *argv[])
{
  const ClutterColor     stage_color     = {100, 100, 100, 255};
  ClutterActor          *stage, *box, *texture;
  GstElement *src, *sink, *pipeline;

  if (!clutter_init(&argc, &argv)) {
    g_printf ("Couldn't init clutter");
    return -1;
  }

  gst_init (&argc, &argv);

  if (!clutter_gst_init (&argc, &argv)) {
    g_printf ("Couldn't init clutter_gst");
    return -1;
  }

  stage = clutter_stage_new ();
  clutter_actor_set_size (stage, 1024.0f, 240.0f);
  clutter_actor_set_background_color (CLUTTER_ACTOR (stage), &stage_color);
  clutter_stage_set_title (CLUTTER_STAGE (stage), "Gst Test");
  clutter_stage_set_user_resizable (CLUTTER_STAGE (stage), TRUE);
  g_signal_connect (stage, "destroy", G_CALLBACK (clutter_main_quit), NULL);

  texture = g_object_new (CLUTTER_TYPE_TEXTURE,
                          "disable-slicing", TRUE,
                          NULL);
  clutter_actor_add_child (CLUTTER_ACTOR (stage), texture);

  sink = gst_element_factory_make ("xvimagesink", NULL);
  //  g_object_set (G_OBJECT (sink), "texture", CLUTTER_TEXTURE(texture), NULL);

  pipeline = gst_pipeline_new("pipeline");

  g_print ("play: %s\n", argv[1]);
  
  src = gst_element_factory_make ("uridecodebin", NULL);
  g_object_set (G_OBJECT (src),"uri", argv[1], NULL);
  gst_bin_add_many (GST_BIN(pipeline), src, sink, NULL);
  if (!gst_element_link (src, sink)) {
    g_print ("listen for newly created pads\n");
    g_signal_connect (src, "pad-added", G_CALLBACK (cb_new_pad), sink);
  }

  gst_element_set_state (pipeline, GST_STATE_PLAYING);

  clutter_actor_show_all (stage);
  clutter_main();
}


