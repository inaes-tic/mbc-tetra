#include <clutter-gst/clutter-gst.h>

ClutterActor *ga_clutter_texture_new (void);
GstBin *ga_audio_bin (gchar *source);
GstElement *ga_pipeline_from_uri (gchar 	*uri,
                                  GstElement    *sink,
                                  gboolean loop);
GstElement *ga_pipeline_from_source (gchar 	**source,
                                     GstElement *sink);
void ga_pipeline_set_sync_handler (GstElement *pipeline,
                                   GstBusSyncHandler func,
                                   gpointer user_data);




