/*
 * Clutter-GStreamer.
 *
 * GStreamer integration library for Clutter.
 *
 * test-alpha.c - Transparent videos.
 *
 * Authored by Damien Lespiau  <damien.lespiau@intel.com>
 *
 * Copyright (C) 2009 Intel Corporation
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the
 * Free Software Foundation, Inc., 59 Temple Place - Suite 330,
 * Boston, MA 02111-1307, USA.
 */

#include <stdlib.h>
#include <string.h>

#include <math.h>

#include <glib/gprintf.h>
#include <clutter-gst/clutter-gst.h>

#include <cheese/cheese.h>
#include <cheese/cheese-camera.h>
#include <cheese/cheese-camera-device.h>
#include <cheese/cheese-camera-device-monitor.h>

#include "ga-utils.h"

/* FIXME: this should be passed around in a general struct. */
ClutterActor *main_actor, **texturea;
gdouble *volume;
guint actors, current_actor = 0;
gboolean sleeping = FALSE;
guint wait_interval = 2000;

static gint   opt_framerate = 30;
static gchar *opt_fourcc    = "I420";
static gint   opt_bpp       = 24;
static gint   opt_depth     = 24;

#define N_RECTS         20

static gboolean is_homogeneous = TRUE;
static gboolean vertical       = FALSE;
static gboolean random_size    = FALSE;
static gboolean fixed_size     = TRUE;

static gint     n_rects        = N_RECTS;
static gint     x_spacing      = 10;
static gint     y_spacing      = 10;

static GOptionEntry options[] =
{
  {
    "random-size", 'r',
    0,
    G_OPTION_ARG_NONE,
    &random_size,
    "Randomly size the rectangles", NULL
  },
  {
    "num-rects", 'n',
    0,
    G_OPTION_ARG_INT,
    &n_rects,
    "Number of rectangles", "RECTS"
  },
  {
    "vertical", 'v',
    0,
    G_OPTION_ARG_NONE,
    &vertical,
    "Set vertical orientation", NULL
  },
  {
    "homogeneous", 'h',
    0,
    G_OPTION_ARG_NONE,
    &is_homogeneous,
    "Whether the layout should be homogeneous", NULL
  },
  {
    "x-spacing", 0,
    0,
    G_OPTION_ARG_INT,
    &x_spacing,
    "Horizontal spacing between elements", "PX"
  },
  {
    "y-spacing", 0,
    0,
    G_OPTION_ARG_INT,
    &y_spacing,
    "Vertical spacing between elements", "PX"
  },
  {
    "fixed-size", 'f',
    0,
    G_OPTION_ARG_NONE,
    &fixed_size,
    "Fix the layout size", NULL
  },
  { NULL }
};

static guint32
parse_fourcc (const gchar *fourcc)
{
  if (strlen (fourcc) != 4)
    return 0;

  return GST_STR_FOURCC (fourcc);
}

static gboolean
wake_up_level_cb (gpointer user_data) {
    gboolean *sleepin = user_data;

    g_print ("WAKE UP!\n");

    *sleepin = FALSE;
    return FALSE;
}

static gboolean
message_handler (GstBus * bus, GstMessage * message, gpointer data)
{
    static guint i = 0;
    guint id = (guint) data;

    if (sleeping)
        return TRUE;

    g_print ("handler %u, got message %u\n", id,  i++);


  if (message->type == GST_MESSAGE_ELEMENT) {
    const GstStructure *s = gst_message_get_structure (message);
    const gchar *name = gst_structure_get_name (s);

    if (strcmp (name, "level") == 0) {
      gint channels;
      GstClockTime endtime;
      gdouble rms_dB, peak_dB, decay_dB;
      gdouble rms;
      const GValue *list;
      const GValue *value;

      gint i, max;

      if (!gst_structure_get_clock_time (s, "endtime", &endtime))
        g_warning ("Could not parse endtime");
      /* we can get the number of channels as the length of any of the value
       * lists */
      list = gst_structure_get_value (s, "rms");
      channels = gst_value_list_get_size (list);

      g_print ("endtime: %" GST_TIME_FORMAT ", channels: %d\n",
          GST_TIME_ARGS (endtime), channels);
      for (i = 0; i < channels; ++i) {
        g_print ("channel %d\n", i);
        list = gst_structure_get_value (s, "rms");
        value = gst_value_list_get_value (list, i);
        rms_dB = g_value_get_double (value);
        /* converting from dB to normal gives us a value between 0.0 and 1.0 */
        rms += pow (10, rms_dB / 20);
        g_print ("    normalized rms value: %f\n", rms);
      }
      volume[id] = rms /= channels;
      for (i = 0; i < actors; i++) {
          max = (volume[id] > volume[i])?id:i;
      }

      if (current_actor != max) {
          g_print ("got new max: %d\nSLEEPING\n", max);

          clutter_clone_set_source (CLUTTER_CLONE(main_actor), texturea[max]);
          current_actor = max;
          sleeping = TRUE;

          g_timeout_add (wait_interval, wake_up_level_cb, &sleeping);
      }
    }
  }
  /* we handled the message we want, and ignored the ones we didn't want.
   * so the core can unref the message for us */

  return TRUE;
}

ClutterActor *actor_from_gst (gchar 		    **source,
                              gchar 		    *uri)
{
    static guint id = 0; /* hack */

    gboolean               result;
    ClutterActor          *texture;
    GstElement		  *sink;

    GstElement		  *pipeline;
    GstBus		  *bus;
    guint watch_id;

  /* We need to set certain props on the target texture currently for
   * efficient/corrent playback onto the texture (which sucks a bit)
   */
    texture = ga_clutter_texture_new ();

  sink = gst_element_factory_make ("cluttersink", NULL);
  g_object_set (G_OBJECT(sink), "texture", CLUTTER_TEXTURE (texture), NULL);

  if (source && source[0]) {
      pipeline = ga_pipeline_from_source (source, sink);
  } else {
      pipeline = ga_pipeline_from_uri (uri, sink, TRUE);
  }

  gst_element_set_state (GST_ELEMENT(pipeline), GST_STATE_PLAYING);

  bus = gst_element_get_bus (GST_ELEMENT(pipeline));
  watch_id = gst_bus_add_watch (bus, message_handler, (void *)id++); /* FIXME: hack */

  clutter_actor_set_size (texture, 320.0f, 240.0f);

  return texture;
}


ClutterActor *setup_clutter_layout (ClutterActor *stage, ClutterActor *clone)
{
    ClutterLayoutManager  *layout, *boxlayout;
    ClutterActor	  *box;
    const ClutterColor     box_color     = {100, 200, 100, 100};

  layout = clutter_box_layout_new ();
  clutter_box_layout_set_homogeneous (CLUTTER_BOX_LAYOUT (layout),
                                       is_homogeneous);
  clutter_box_layout_set_spacing (CLUTTER_BOX_LAYOUT (layout),
                                          x_spacing);
  clutter_box_layout_set_orientation (CLUTTER_BOX_LAYOUT (layout),
                                      CLUTTER_ORIENTATION_VERTICAL);

  box = clutter_actor_new ();
  clutter_actor_set_background_color (CLUTTER_ACTOR (box), &box_color);

  boxlayout = clutter_box_layout_new ();
  clutter_box_layout_set_homogeneous (CLUTTER_BOX_LAYOUT (boxlayout),
                                       is_homogeneous);
  clutter_box_layout_set_spacing (CLUTTER_BOX_LAYOUT (boxlayout),
                                          x_spacing);

  //g_object_set (G_OBJECT (box), "y-expand", TRUE, NULL);
  //  g_object_set (G_OBJECT (box), "y-fill", TRUE, NULL);


  clutter_actor_set_layout_manager (box, boxlayout);
  clutter_actor_set_layout_manager (stage, layout);

  /*  g_object_set (G_OBJECT (clone), "x-expand", TRUE, NULL);
      g_object_set (G_OBJECT (clone), "y-expand", TRUE, NULL);*/
  /*  g_object_set (G_OBJECT (clone), "x-fill", TRUE, NULL);
      g_object_set (G_OBJECT (clone), "y-fill", TRUE, NULL);*/


  clutter_actor_add_child (stage, clone);
  clutter_actor_add_child (stage, box);

  return box;
}

void
list_camera_cb (gpointer data, gpointer user_data)
{
    CheeseCameraDevice *camdev = data;
    g_print ("found camera: %s\n", cheese_camera_device_get_name (camdev));
    g_object_unref (G_OBJECT (camdev));
}

void
cheese_camera_plugged_cb (CheeseCameraDeviceMonitor *monitor,
                          CheeseCameraDevice        *device,
                          gpointer                   user_data)
{
    GHashTable *cameras = user_data;

    g_print ("found camera: '%s'\n", cheese_camera_device_get_name (device));
    g_hash_table_insert (cameras,
                         (void *) cheese_camera_device_get_uuid (device),
                         device);
}

void
cheese_camera_unplugged_cb (CheeseCameraDeviceMonitor *monitor,
                            gchar                     *uuid,
                            gpointer                   user_data)
{
    GHashTable *cameras = user_data;

    g_hash_table_remove (cameras, uuid);

    g_print ("removed camera: '%s'\n", uuid);
}

GHashTable *
cheese_get_cameras_hash (void)
{
    GHashTable			*cameras;
    CheeseCameraDeviceMonitor   *cam_mon;

    g_printerr ("initing cameras");

    cameras = g_hash_table_new (g_str_hash, g_str_equal);

    cam_mon = cheese_camera_device_monitor_new();
    g_signal_connect (G_OBJECT (cam_mon), "added",
                      G_CALLBACK(cheese_camera_plugged_cb), cameras);
    g_signal_connect (G_OBJECT (cam_mon), "removed",
                      G_CALLBACK(cheese_camera_unplugged_cb), cameras);

    cheese_camera_device_monitor_coldplug (cam_mon);

    return cameras;
}

CheeseCamera *
cheese_init_cam (GHashTable *cameras, ClutterActor *texture)
{
    GHashTableIter iter;
    gpointer key, value;

    g_hash_table_iter_init (&iter, cameras);
    while (g_hash_table_iter_next (&iter, &key, &value)) {
        GError                  *error = NULL;
        gchar			*uuid = key;
        CheeseCamera 		*cam;
        CheeseCameraDevice	*device = value;
        CheeseVideoFormat	*format;

        format = cheese_camera_device_get_best_format (device);
        g_assert (format);
        g_assert (texture);

        cam = cheese_camera_new (CLUTTER_TEXTURE(texture),
                                 cheese_camera_device_get_device_node (device),
                                 format->width/4, format->height/4);
        clutter_actor_set_size (texture, format->width/4, format->height/4);

        g_print ("got cameras: %p, texture: %p, %d x %d\n", cameras, texture,
                 format->width, format->height);
        g_print ("running cam: %s: %s\n", uuid, cheese_camera_device_get_device_node (device));

        cheese_camera_setup (cam, uuid, &error);

        if (error) {
            g_print ("%s\n", error->message);
            g_error_free (error);
            return NULL;
        }

        cheese_camera_play (cam);
        //        g_object_unref (G_OBJECT (format));

        return cam;
    }

    return NULL;
}


int
main (int argc, char *argv[])
{
  GError                *error = NULL;
  gboolean               result;
  gint		         i;
  gchar *s1[2] = {"v4l2src", "pulsesrc"};
  gchar *s2[2] = {"videotestsrc", NULL};

  const ClutterColor     stage_color     = {100, 100, 100, 255};
  ClutterActor          *stage, *box, *texture;
  ClutterLayoutManager  *layout;
  ClutterConstraint	*constraint;

  GHashTable		*cameras;
  CheeseCamera		*cam;

  //  cheese_gtk_init (&argc, &argv);
  if (!clutter_init(&argc, &argv)) {
    g_printf ("Couldn't init clutter");
    return -1;
  }

  gst_init (&argc, &argv);
  cheese_init (&argc, &argv);
  /*
  result = clutter_gst_init_with_args (&argc,
                                       &argv,
                                       "TetraPack - Malbec barato para todos",
                                       options,
                                       NULL,
                                       &error);
  if (error)
    {
      g_print ("%s\n", error->message);
      g_error_free (error);
      return EXIT_FAILURE;
    }
x  */
  /*
  actors = 2 + argc;

  texturea = g_alloca (sizeof (ClutterActor *) * actors);
  volume  = g_alloca (sizeof (gfloat) * actors);
  memset (volume, 0, sizeof(gfloat) *actors);

  stage = clutter_stage_new ();
  clutter_actor_set_size (stage, 1024.0f, 240.0f);
  clutter_actor_set_background_color (CLUTTER_ACTOR (stage), &stage_color);
  clutter_stage_set_title (CLUTTER_STAGE (stage), "Gst Hangout");
  clutter_stage_set_user_resizable (CLUTTER_STAGE (stage), TRUE);
  g_signal_connect (stage, "destroy", G_CALLBACK (clutter_main_quit), NULL);

  texture = g_object_new (CLUTTER_TYPE_TEXTURE,
                          "disable-slicing", TRUE,
                          NULL);
  */
  cameras = cheese_get_cameras_hash ();
  //  cam = cheese_init_cam (cameras, texture);
  /*
  texturea[0] = texture; //actor_from_gst (s1, NULL);
  texturea[1] = actor_from_gst (s2, NULL);

  main_actor = clutter_clone_new (texturea[0]);
  box = setup_clutter_layout (stage, main_actor);
  //  mic_audio();

  clutter_actor_add_child (CLUTTER_ACTOR (box), texturea[0]);
  clutter_actor_add_child (CLUTTER_ACTOR (box), texturea[1]);

  for (i = 1; i < argc; i++) {
      gchar *path = g_strconcat("file:///", argv[i], NULL);

      g_print ("--> %s\n", path);
      texturea[i+1] = actor_from_gst (NULL, path);
      /*      constraint = clutter_bind_constraint_new (box, CLUTTER_BIND_SIZE, 0.0);
              clutter_actor_add_constraint_with_name (texturea[i+1], "size", constraint);*\/
      clutter_actor_add_child (CLUTTER_ACTOR (box), texturea[i+1]);
      g_free (path);
  }

  clutter_actor_show_all (stage);
*/
  clutter_main();

  return EXIT_SUCCESS;
}
