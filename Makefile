#!/usr/bin/make

CC=clang
PKGF = `pkg-config --cflags --libs clutter-gtk-1.0 clutter-gst-1.0 cheese`
CFLAGS=-ggdb -O0 ${PKGF}


clutter-test:
	${CC} ${CFLAGS} ga-utils.c gsthangout.c -o clutter-test
