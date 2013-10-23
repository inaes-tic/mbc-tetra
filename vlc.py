import sys
import os
import subprocess
import logging

import gi.repository
from gi.repository import GObject

import config

class Vlc(GObject.GObject):
    def __init__(self, params=None, silent=True):
        GObject.GObject.__init__(self)

        self.config = config.get('StreamingOut', {})
        self._subproc = None
        self.silent = silent
        self.set_params(params)
        pass

    def start(self):
        if self._subproc is None:
            return
        self._subproc.stdin.write('play\n')

    def pause(self):
        if self._subproc is None:
            return
        self._subproc.stdin.write('pause\n')

    def stop(self):
        if self._subproc is None:
            return
        self._subproc.stdin.write('stop\n')

    def kill(self):
        if self._subproc is None:
            return
        self.stop()
        self._subproc.terminate()
        self._subproc = None

    def launch(self):
        self.kill()
        params = ['cvlc', '-R', '-I rc', 'tcp://127.0.0.1:9078']
        duplicate_mods = []

        def parse_http(fmt):
            conf = self.config.setdefault('http_%s' % fmt, {})
            enabled = conf.setdefault('enabled', True)
            host = conf.setdefault('host', '')
            port = conf.setdefault('port', '8080')
            path = conf.setdefault('path', 'vivo.%s' % fmt)
            path = os.path.join('/', path)

            if enabled:
                mod = ' dst=http{ dst=%s:%s%s , mux=%s } ' % (host, port, path, fmt)
                duplicate_mods.append(mod)

        def parse_rtsp():
            conf = self.config.setdefault('rtsp', {})
            enabled = conf.setdefault('enabled', True)
            rtsp_host = conf.setdefault('rtsp_host', '239.255.0.1')
            rtsp_port = conf.setdefault('rtsp_port', '5004')
            sdp_host = conf.setdefault('sdp_host', '0.0.0.0')
            sdp_port = conf.setdefault('sdp_port', '8080')
            sdp_path = conf.setdefault('sdp_path', 'tetra.sdp')
            sdp_path = os.path.join('/', sdp_path)
            sap_name = conf.setdefault('sap_name', 'Tetra')
            ttl = conf.setdefault('ttl', '2')

            if enabled:
                mod = ' dst=rtp{ dst=%s , port=%s , sdp=rtsp://%s:%s:%s , sap , name="%s" , ttl=%s , mux=ts } ' % (rtsp_host, rtsp_port, sdp_host, sdp_port, sdp_path, sap_name, ttl)
                params.append('--sap-interval=1')
                params.append('--rtsp-host=%s' % rtsp_host)
                duplicate_mods.append(mod)

        for fmt in ['flv']:
            parse_http(fmt)

        parse_rtsp()

        if duplicate_mods:
            mods = '#duplicate{ %s }' % ','.join(duplicate_mods)
            params.append('--sout')
            params.append(mods)

        if self.params:
            params.extend(self.params)

        logging.debug('Vlc: about to run with args: %s', params)
        if self.silent:
            devnull = open(os.devnull, 'w')
            ret = subprocess.Popen(params, stdin=subprocess.PIPE, stdout=devnull, stderr=devnull)
        else:
            ret = subprocess.Popen(params, stdin=subprocess.PIPE)

        if ret:
            self._subproc = ret

    def set_params(self, params):
        self.params = params


if __name__ == '__main__':
    v = Vlc(silent=False)
    v.launch()
    v._subproc.wait()

