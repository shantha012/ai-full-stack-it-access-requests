"""Single-host SQLite source revisions, work claims and immutable results.

Provider calls happen outside transactions. Different concurrent source revisions
are rejected for operator resolution rather than assigned an invented ordering.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shlex
import sqlite3
import time
import uuid

from .intake import process_response, route
from .prompts import build_messages
from .sources import Source


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self.connection() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS revisions (
              document TEXT, hash TEXT, raw BLOB NOT NULL, PRIMARY KEY(document, hash));
            CREATE TABLE IF NOT EXISTS attempts (
              id INTEGER PRIMARY KEY, document TEXT NOT NULL, hash TEXT NOT NULL,
              config TEXT NOT NULL, config_hash TEXT NOT NULL, policy TEXT NOT NULL,
              policy_hash TEXT NOT NULL, state TEXT NOT NULL, result TEXT,
              token TEXT, lease REAL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS current (document TEXT PRIMARY KEY, attempt INTEGER NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, source, *, config=None, policy=None, force=False):
        config = config or {'provider': 'mock'}
        policy = policy or {'office_policy': (Path(__file__).resolve().parents[1] /
                                             'materials/office-policy.md').read_text()}
        fingerprint = digest({'settings': config, 'prompt': build_messages('')[0],
                              'schema': (Path(__file__).resolve().parents[1] / 'snapshot.schema.json').read_text()})
        policy_hash = digest(policy)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT a.* FROM attempts a JOIN current c ON c.attempt=a.id WHERE c.document=?',
                             (source.document_id,)).fetchone()
            if old and old['state'] in ('pending', 'running'):
                if old['hash'] != source.source_sha256 or old['config_hash'] != fingerprint or old['policy_hash'] != policy_hash:
                    raise ValueError('Unfinished competing revision/settings; resolve existing work before replacing it')
                return old['id']
            if old and not force and (old['hash'], old['config_hash'], old['policy_hash']) == (source.source_sha256, fingerprint, policy_hash):
                return old['id']
            db.execute('INSERT OR IGNORE INTO revisions VALUES (?,?,?)',
                       (source.document_id, source.source_sha256, source.raw_bytes))
            attempt = db.execute('''INSERT INTO attempts
              (document,hash,config,config_hash,policy,policy_hash,state,created)
              VALUES (?,?,?,?,?,?,?,?)''', (source.document_id, source.source_sha256,
              json.dumps(config), fingerprint, json.dumps(policy), policy_hash, 'pending', self.clock())).lastrowid
            db.execute('INSERT OR REPLACE INTO current VALUES (?,?)', (source.document_id, attempt))
            # Policy-only refresh retains the validated extraction and its settings.
            if old and not force and old['hash'] == source.source_sha256 and old['config_hash'] == fingerprint and old['result']:
                previous = json.loads(old['result'])
                if previous['extraction'] is not None:
                    extraction = previous['extraction']
                    status, owner, action = route(source, extraction)
                    previous.update(status=status, owner=owner, next_action=action)
                    token = uuid.uuid4().hex
                    db.execute("UPDATE attempts SET state='running',token=? WHERE id=?", (token, attempt))
                    self._publish(db, attempt, token, previous)
            return attempt

    def claim(self, attempt, *, lease_seconds=120):
        token = uuid.uuid4().hex
        with self.connection() as db:
            updated = db.execute("UPDATE attempts SET state='running', token=?, lease=? WHERE id=? AND state='pending'",
                                 (token, self.clock() + lease_seconds, attempt)).rowcount
        return token if updated else None

    def _publish(self, db, attempt, token, record):
        row = db.execute('SELECT * FROM attempts WHERE id=?', (attempt,)).fetchone()
        if row['state'] != 'running' or row['token'] != token:
            return False
        if db.execute('SELECT attempt FROM current WHERE document=?', (row['document'],)).fetchone()[0] != attempt:
            return False
        record = dict(record)
        policy = json.loads(row['policy'])
        if record['owner'] == 'System Owner':
            record['owner'] = policy.get('system_owner', 'System Owner')
        record.update(attempt_id=attempt, state='completed', provenance=dict(
            extraction_hash=row['config_hash'], producing_config=json.loads(row['config']),
            policy_hash=row['policy_hash'], policy=policy))
        if record['error'] is not None:
            record['retry_command'] = ('python3 -m access_requests retry --db ' + shlex.quote(str(self.path)) +
                                       ' --document ' + shlex.quote(row['document']))
        db.execute("UPDATE attempts SET state='completed', result=?, token=NULL, lease=NULL WHERE id=?",
                   (json.dumps(record), attempt))
        return True

    def publish(self, attempt, token, record):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._publish(db, attempt, token, record)

    def source_bytes(self, document, source_hash):
        with self.connection() as db:
            return db.execute('SELECT raw FROM revisions WHERE document=? AND hash=?', (document, source_hash)).fetchone()[0]

    def source_for(self, attempt):
        with self.connection() as db:
            row = db.execute('SELECT * FROM attempts WHERE id=?', (attempt,)).fetchone()
        raw = self.source_bytes(row['document'], row['hash'])
        return Source(row['document'], row['hash'], raw, json.loads(raw)['message'])

    def result(self, attempt):
        with self.connection() as db:
            row = db.execute('SELECT * FROM attempts WHERE id=?', (attempt,)).fetchone()
        return json.loads(row['result']) if row['result'] else dict(
            document_id=row['document'], source_sha256=row['hash'], attempt_id=row['id'], state=row['state'])

    def process(self, source, provider, *, config=None, policy=None, force=False):
        attempt = self.enqueue(source, config=config, policy=policy, force=force)
        token = self.claim(attempt)
        if token:
            reply = provider.extract(source.message)
            self.publish(attempt, token, process_response(source, reply))
        return self.result(attempt)

    def queue(self):
        with self.connection() as db:
            ids = [r[0] for r in db.execute('SELECT attempt FROM current ORDER BY document')]
        return [self.result(i) for i in ids]

    def history(self, document):
        with self.connection() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM attempts WHERE document=? ORDER BY id', (document,))]
        return [self.result(i) for i in ids]
