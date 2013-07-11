#!/bin/bash
cvlc -R tcp://127.0.0.1:9078 --sout '#http{mux=ffmpeg{mux=flv},dst=:8080/vivo}'

