"""Offline-only acceptance helpers; expected facts live in tests, never measured runs."""
import json
import socket
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
MOCKS = ROOT / 'test/mock_responses'

def reply(name):
    return json.loads((MOCKS / (name + '.json')).read_text())

class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(socket, 'socket', side_effect=AssertionError('network prohibited'))
        self.guard.start()
        self.addCleanup(self.guard.stop)

def run_case(number, saved=None):
    from access_requests.intake import read_document
    from access_requests.provider import MockProvider
    from access_requests.pipeline import process
    doc = read_document(ROOT / f'materials/requests/IT-{number:03}.json')
    return process(doc, MockProvider(MOCKS, [saved or f'it-{number:03}']))
