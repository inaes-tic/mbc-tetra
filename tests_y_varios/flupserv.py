#!/usr/bin/env python

# XXX copypasta desde http://synack.me/blog/implementing-http-live-streaming

from flup.server.fcgi import WSGIServer
from threading import Thread
from socket import socket
from select import select
from Queue import Queue
import re

class LiveHTTPServer(object):
    def __init__(self):
        self.urls = [
            ('^/stream.m3u8$', self.playlist),
            ('^/stream.ts$', self.stream),
        ]
        self.urls = [(re.compile(pattern), func) for pattern, func in self.urls]
        self.queues = []

    def __call__(self, environ, start_response):
        return self.stream(start_response, 'xxx')
        for pattern, func in self.urls:
            match = pattern.match(environ['PATH_INFO'])
            if match:
                return func(start_response, match)
        start_response('404 Not Found', [('Content-type', 'text/plain')])
        return ['404 Not Found']

    def playlist(self, start_response, match):
        start_response('200 OK', [('Content-type', 'application/x-mpegURL')])
        return ['''#EXTM3U
    #EXTINF:10,
    http://127.0.0.1:1234/stream.ts
    #EXT-X-ENDLIST''']

    def stream(self, start_response, match):
        print 'stream'
        start_response('200 OK', [('Content-type', 'video/MP2T')])
        q = Queue()
        self.queues.append(q)
        while True:
            try:
                yield q.get()
            except:
                if q in self.queues:
                    self.queues.remove(q)
                return

def input_loop(app):
    sock = socket()
    sock.bind(('', 9999))
    sock.listen(1)
    while True:
        print 'Waiting for input stream'
        sd, addr = sock.accept()
        print 'Accepted input stream from', addr
        data = True
        while data:
            readable = select([sd], [], [], 0.1)[0]
            for s in readable:
                data = s.recv(1024)
                if not data:
                    print 'xx'
                    break
                for q in app.queues:
                    q.put(data)
        print 'Lost input stream from', addr

if __name__ == '__main__':
    app = LiveHTTPServer()
    server = WSGIServer(app, bindAddress=('', 9998))

    t1 = Thread(target=input_loop, args=[app])
    t1.setDaemon(True)
    t1.start()

    server.run()
