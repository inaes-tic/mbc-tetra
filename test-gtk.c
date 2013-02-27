#include <glib/gprintf.h>
#include <gst/gst.h>
#include <gtk/gtk.h>
#include <clutter/clutter.h>
#include <clutter-gtk/clutter-gtk.h>
#include <clutter-gst/clutter-gst.h>

ClutterActor * gtk_clutter_texture (void) {
     GtkWidget *button = gtk_button_new_with_label ("hello");
     return gtk_clutter_actor_new_with_contents (button);
}

ClutterActor * gst_clutter_texture (void) {
     ClutterActor 	*texture = clutter_texture_new();
     GstElement		*sink    = gst_element_factory_make ("cluttersink", NULL);
     GstElement		*src     = gst_element_factory_make ("videotestsrc", NULL);
     GstElement		*pipeline= gst_pipeline_new ("pipeline");

     g_object_set (G_OBJECT (sink), "texture", CLUTTER_TEXTURE(texture), NULL);
     gst_bin_add_many (GST_BIN(pipeline), src, sink, NULL);

     if (! gst_element_link (src, sink))
	  g_error ("Couldn't link SRC and SINK\n");

     gst_element_set_state (pipeline, GST_STATE_PLAYING);

     return texture;
}

int main (int argc, char *argv[]) {
  GtkWidget 	*window; 
  GtkWidget 	*clutter;
  ClutterActor 	*stage;

  gtk_init(&argc, &argv);
  gst_init(&argc, &argv);
  if (gtk_clutter_init (&argc, &argv) != CLUTTER_INIT_SUCCESS)
    g_error ("Unable to initialize GtkClutter");

  if (!clutter_gst_init (&argc, &argv))
    g_error ("Couldn't init clutter_gst");

  window = gtk_window_new (GTK_WINDOW_TOPLEVEL);
  clutter= gtk_clutter_embed_new ();
  stage  = gtk_clutter_embed_get_stage (GTK_CLUTTER_EMBED(clutter));

  g_signal_connect (window, "destroy", G_CALLBACK(gtk_main_quit), NULL);  
  gtk_container_add (GTK_CONTAINER(window), clutter);

  clutter_actor_add_child (stage, gtk_clutter_texture ());
  clutter_actor_add_child (stage, gst_clutter_texture ());

  gtk_widget_show_all (GTK_WIDGET (window));
  gtk_main();
}



