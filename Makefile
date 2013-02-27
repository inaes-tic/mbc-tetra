#!/usr/bin/make

CC=clang
PKGF = `pkg-config --cflags --libs gstreamer-1.0 clutter-gst-2.0 clutter-gtk-1.0`
CFLAGS=-ggdb -O0 ${PKGF} 

test-gtk: test-gtk.o
	${CC} ${CFLAGS} test-gtk.c -o test-gtk
test: test.o
	${CC} ${CFLAGS} test.c -o test

clutter-test:
	${CC} ${CFLAGS} ga-utils.c gsthangout.c -o clutter-test

clean:
	rm -rf clutter-test
