"""Offline subprocess harness. Controls timing, never business responses."""
import os
from pathlib import Path
import runpy
import socket
import sys
import time
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
original = type(os.environ).__getitem__
def guarded(environ, key):
    if key == 'API_KEY':
        raise AssertionError('subprocess read API_KEY')
    return original(environ, key)
def forbidden(*args, **kwargs):
    raise AssertionError('subprocess attempted network')
type(os.environ).__getitem__ = guarded
socket.socket = socket.create_connection = urllib.request.urlopen = forbidden
from access_requests.providers import MockProvider
extract = MockProvider.extract
control = os.environ.get('TEST_CONTROL')
def controlled(self, message):
    if control:
        directory = Path(control)
        name = 'IT-002' if 'IT-002' in message else 'IT-001'
        with (directory / 'calls').open('a') as log:
            log.write(name + '\n')
        if (directory / ('hold-' + name)).exists():
            (directory / ('entered-' + name)).touch()
            deadline = time.monotonic() + 15
            while not (directory / ('release-' + name)).exists():
                if time.monotonic() > deadline:
                    raise AssertionError('test failed to release process')
                time.sleep(.01)
    return extract(self, message)
MockProvider.extract = controlled
runpy.run_module('access_requests', run_name='__main__')
