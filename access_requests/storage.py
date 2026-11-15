"""SQLite history and consistent POSIX-local snapshot publication."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

QUEUE_FIELDS = ('document_id','attempt_id','source_sha256','settings_fingerprint','policy_version',
                'status','owner','next_action','snapshot_generation')

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY, raw BLOB NOT NULL, source_sha256 TEXT NOT NULL,
                    current_attempt INTEGER);
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                INSERT OR IGNORE INTO metadata VALUES ('version',0);
                CREATE TRIGGER IF NOT EXISTS immutable_attempt_update BEFORE UPDATE ON attempts
                    BEGIN SELECT RAISE(ABORT,'immutable attempt'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_attempt_delete BEFORE DELETE ON attempts
                    BEGIN SELECT RAISE(ABORT,'immutable attempt'); END;
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, document, result, settings=None):
        from .config import Settings
        settings=settings or Settings()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            next_id = db.execute('SELECT COALESCE(MAX(attempt_id),0)+1 FROM attempts').fetchone()[0]
            record = dict(result,attempt_id=next_id,settings_fingerprint=settings.fingerprint,policy_version=settings.policy_version,
                          producing_settings=settings.public())
            db.execute('INSERT INTO attempts VALUES (?,?,?,?)',
                       (next_id,document.document_id,document.source_sha256,json.dumps(record)))
            db.execute('INSERT INTO documents VALUES (?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET '
                       'raw=excluded.raw, source_sha256=excluded.source_sha256, current_attempt=excluded.current_attempt',
                       (document.document_id,document.raw,document.source_sha256,next_id))
            db.execute("UPDATE metadata SET value=value+1 WHERE key='version'")
        return record

    def _current(self, db):
        return [json.loads(r[0]) for r in db.execute('SELECT a.record FROM documents d JOIN attempts a '
                'ON a.attempt_id=d.current_attempt ORDER BY d.document_id')]

    def current(self):
        with self.connect() as db:
            return self._current(db)

    def attempts(self, document_id=None):
        with self.connect() as db:
            query='SELECT record FROM attempts'
            params=()
            if document_id:
                query+=' WHERE document_id=?'; params=(document_id,)
            return [json.loads(r[0]) for r in db.execute(query+' ORDER BY attempt_id',params)]

    def export(self, destination):
        destination = Path(destination).absolute()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (destination.parent / ('.'+destination.name+'.lock')).open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            with self.connect() as db:
                db.execute('BEGIN')
                version=db.execute("SELECT value FROM metadata WHERE key='version'").fetchone()[0]
                records=[dict(r,snapshot_generation=version) for r in self._current(db)]
            generations=destination.parent/('.'+destination.name+'-generations')
            generations.mkdir(exist_ok=True)
            generation=Path(tempfile.mkdtemp(prefix=f'{version}-',dir=generations))
            files={'extractions.jsonl':''.join(json.dumps(r)+'\n' for r in records),
                   'queue.json':json.dumps([{k:r[k] for k in QUEUE_FIELDS} for r in records],indent=2)+'\n'}
            for name, contents in files.items():
                with (generation/name).open('w') as stream:
                    stream.write(contents); stream.flush(); os.fsync(stream.fileno())
            temporary=destination.parent/('.'+destination.name+'-'+uuid.uuid4().hex)
            temporary.symlink_to(generation.relative_to(destination.parent), target_is_directory=True)
            os.replace(temporary,destination)
            return generation

    def document(self, document_id):
        from .intake import Document
        with self.connect() as db:
            row=db.execute('SELECT * FROM documents WHERE document_id=?',(document_id,)).fetchone()
        if row is None:
            raise KeyError(document_id)
        return Document(row['document_id'],row['source_sha256'],json.loads(row['raw'])['message'],row['raw'])

    def reusable(self, document, settings):
        with self.connect() as db:
            row=db.execute('SELECT a.record FROM documents d JOIN attempts a ON a.attempt_id=d.current_attempt '
                           'WHERE d.document_id=? AND a.source_sha256=?',
                           (document.document_id,document.source_sha256)).fetchone()
        record=json.loads(row[0]) if row else None
        return record if record and record['settings_fingerprint']==settings.fingerprint else None
