#!/usr/bin/make

CC=clang
PKGF = `pkg-config --cflags --libs clutter-gtk-1.0 clutter-gst-1.0 cheese`
CFLAGS=-ggdb -O0 ${PKGF}


gtk:
	${CC} ${CFLAGS} ga-utils.c gtk-hangout.c -o gtk-test

clutter:
	${CC} ${CFLAGS} ga-utils.c gsthangout.c -o clutter-test
