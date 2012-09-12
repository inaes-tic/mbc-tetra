#include <glib/gprintf.h>
#include <clutter-gst/clutter-gst.h>

/* HACK: kill me */
static gint   opt_framerate = 30;
static gchar *opt_fourcc    = "I420";

void
ga_pipeline_set_sync_handler (GstElement *pipeline,
                              GstBusSyncHandler func,
                              gpointer user_data)
{
    GstBus *bus;

    bus = gst_pipeline_get_bus (GST_PIPELINE (pipeline));
    gst_bus_set_sync_handler (bus, func, user_data);
    gst_object_unref (bus);
}


static void
ga_size_change (ClutterTexture *texture,
             gint            width,
             gint            height,
             gpointer        user_data)
{
  ClutterActor *stage;
  gfloat new_x, new_y, new_width, new_height;
  gfloat stage_width, stage_height;

  stage = clutter_actor_get_stage (CLUTTER_ACTOR (texture));
  if (stage == NULL)
    return;

  clutter_actor_get_size (stage, &stage_width, &stage_height);

  new_height = (height * stage_width) / width;
  if (new_height <= stage_height)
    {
      new_width = stage_width;

      new_x = 0;
      new_y = (stage_height - new_height) / 2;
    }
  else
    {
      new_width  = (width * stage_height) / height;
      new_height = stage_height;

      new_x = (stage_width - new_width) / 2;
      new_y = 0;
    }

  clutter_actor_set_position (CLUTTER_ACTOR (texture), new_x, new_y);
  clutter_actor_set_size (CLUTTER_ACTOR (texture), new_width, new_height);
}


ClutterActor *ga_clutter_texture_new (void)
{
    ClutterActor *texture = g_object_new (CLUTTER_TYPE_TEXTURE,
                                          "disable-slicing", TRUE,
                                          NULL);

    g_signal_connect (CLUTTER_TEXTURE (texture),
                      "size-change",
                      G_CALLBACK (ga_size_change), NULL);

    return texture;
}

GstBin *ga_audio_bin (gchar *source)
{
    gboolean               result;

    GstBin           	  *bin;
    GstPad		  *pad;

    GstElement            *src;
    GstElement            *vol;
    GstElement		  *ac;
    GstElement		  *level;
    GstElement            *sink;

  /* Set up bin */
  bin = GST_BIN(gst_bin_new (NULL));

  if (source)
      src = gst_element_factory_make (source, NULL);
  level = gst_element_factory_make ("level", NULL);
  vol   = gst_element_factory_make ("volume", NULL);
  ac    = gst_element_factory_make ("audioconvert", NULL);

  sink = gst_element_factory_make ("fakesink", NULL);

  g_assert (level); g_assert (ac); g_assert (sink);

  gst_bin_add_many (GST_BIN (bin), level, vol, ac, sink, NULL);
  result = gst_element_link_many (level, vol, ac, sink, NULL);


  if (result == FALSE) {
      g_critical("Could not link elements, in audio pipeline");
      abort();
  }

  if (source) {
      gst_bin_add (GST_BIN (bin), src);
      result = gst_element_link (src, level);

      if (result == FALSE) {
          g_critical("Could not link '%s' source to level, in audio pipeline", source);
          abort();
     }
  }

  gst_element_add_pad (GST_ELEMENT(bin), gst_ghost_pad_new(NULL, gst_bin_find_unlinked_pad (GST_BIN(bin), GST_PAD_SRC)));
  gst_element_add_pad (GST_ELEMENT(bin), gst_ghost_pad_new(NULL, gst_bin_find_unlinked_pad (GST_BIN(bin), GST_PAD_SINK)));

  /* make sure we'll get messages */
  g_object_set (G_OBJECT (level), "message", TRUE, NULL);

  return bin;
}

/* FIXME: this doesn't actually work */
static void
ga_playbin_loop_cb (GstElement *playbin, gpointer user_data)
{
    gchar *uri = user_data;

    g_object_set (G_OBJECT (playbin), "uri", uri, NULL);
}

GstElement *ga_pipeline_from_uri (gchar 	*uri,
                                  GstElement    *sink,
                                  gboolean loop)
{
    GstElement		  *pipeline;
    GstElement		  *audiobin;

    /* Set up pipeline */
    pipeline = gst_element_factory_make ("playbin", NULL);
    g_object_set (G_OBJECT (pipeline), "uri", uri, NULL);

    audiobin = GST_ELEMENT(ga_audio_bin (NULL));

    g_object_set (G_OBJECT (pipeline), "video-sink", sink, NULL);
    g_object_set (G_OBJECT (pipeline), "audio-sink", audiobin, NULL);

    g_signal_connect (G_OBJECT (pipeline), "about-to-finish",
                      G_CALLBACK(ga_playbin_loop_cb), uri);

    return pipeline;
}


GstElement *ga_pipeline_from_source (gchar 	**source,
                                     GstElement *sink)
{
    gboolean               result;
    GstElement		  *pipeline;
    GstElement            *src;
    GstElement            *tee;
    GstElement		  *audiobin;

    GstElement            *capsfilter;
    GstCaps               *caps;

    pipeline = gst_pipeline_new (NULL);
    capsfilter = gst_element_factory_make ("capsfilter", NULL);
    /* make videotestsrc spit the format we want */

    caps = gst_caps_new_simple ("video/x-raw",
                                "format", G_TYPE_STRING,
                                opt_fourcc,
                                "framerate", GST_TYPE_FRACTION,
                                opt_framerate, 1,
                                NULL);

    g_object_set (capsfilter, "caps", caps, NULL);
    g_printf ("%s: [caps] %s\n", __FILE__, gst_caps_to_string (caps));

    src = gst_element_factory_make (source[0], NULL);
    tee = gst_element_factory_make ("tee", "tee");

    gst_bin_add_many (GST_BIN(pipeline), src, capsfilter, tee, sink, NULL);
    if (source[1]) {
        audiobin = GST_ELEMENT(ga_audio_bin (source[1]));
        gst_bin_add (GST_BIN(pipeline), audiobin);
    }

    result = gst_element_link_many (src, tee, sink, NULL);
    if (result == FALSE)
        g_critical ("Could not link elements");

    return pipeline;
}
