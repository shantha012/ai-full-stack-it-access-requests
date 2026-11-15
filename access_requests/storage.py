"""SQLite history and consistent POSIX-local snapshot publication."""
from contextlib import contextmanager
import fcntl
import json
import os
import shlex
from pathlib import Path
import sqlite3
import tempfile
import time
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
                CREATE INDEX IF NOT EXISTS attempts_job ON attempts(json_extract(record,'$.source_generation'));
                CREATE TRIGGER IF NOT EXISTS immutable_attempt_update BEFORE UPDATE ON attempts
                    BEGIN SELECT RAISE(ABORT,'immutable attempt'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_attempt_delete BEFORE DELETE ON attempts
                    BEGIN SELECT RAISE(ABORT,'immutable attempt'); END;
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL, raw BLOB NOT NULL, settings TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    token TEXT, expires REAL);
            ''')
            columns={r[1] for r in db.execute('PRAGMA table_info(documents)')}
            if 'desired_job' not in columns:
                db.execute('ALTER TABLE documents ADD COLUMN desired_job INTEGER')

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
            db.execute('INSERT INTO documents (document_id,raw,source_sha256,current_attempt) VALUES (?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET '
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
            # A brief write reservation serializes state changes through publication.
            # No provider call occurs here. A crash can leave an unreferenced generation.
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                version=db.execute("SELECT value FROM metadata WHERE key='version'").fetchone()[0]
                records=[dict(r,snapshot_generation=version) for r in self._current(db)]
                generations=destination.parent/('.'+destination.name+'-generations')
                generations.mkdir(exist_ok=True)
                generation=Path(tempfile.mkdtemp(prefix=f'{version}-',dir=generations))
                files={'extractions.jsonl':''.join(json.dumps(r)+'\n' for r in records),
                       'queue.json':json.dumps([{k:r[k] for k in QUEUE_FIELDS} for r in records],indent=2)+'\n'}
                reports=Path(__file__).resolve().parents[1]/'reports'
                for name in ('accuracy.md','request-evidence.json','verification.md'):
                    if (reports/name).is_file(): files[name]=(reports/name).read_text()
                for name, contents in files.items():
                    with (generation/name).open('w') as stream:
                        stream.write(contents); stream.flush(); os.fsync(stream.fileno())
                self._sync_directory(generation)
                self._sync_directory(generations)
                temporary=destination.parent/('.'+destination.name+'-'+uuid.uuid4().hex)
                temporary.symlink_to(generation.relative_to(destination.parent), target_is_directory=True)
                os.replace(temporary,destination)
                self._sync_directory(destination.parent)
                return generation

    @staticmethod
    def _sync_directory(path):
        descriptor=os.open(path,os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)

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

    def register(self, document, settings, force=False):
        """Register desired work before calling providers; job IDs define source order."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            desired=db.execute('SELECT j.* FROM documents d JOIN jobs j ON j.job_id=d.desired_job '
                               'WHERE d.document_id=?',(document.document_id,)).fetchone()
            if (not force and desired and desired['source_sha256']==document.source_sha256
                    and desired['fingerprint']==settings.fingerprint):
                return desired['job_id']
            job_id=db.execute('INSERT INTO jobs (document_id,source_sha256,raw,settings,fingerprint) '
                              'VALUES (?,?,?,?,?)',(document.document_id,document.source_sha256,
                              document.raw,json.dumps(settings.public()),settings.fingerprint)).lastrowid
            db.execute('INSERT INTO documents (document_id,raw,source_sha256,desired_job) VALUES (?,?,?,?) '
                       'ON CONFLICT(document_id) DO UPDATE SET raw=excluded.raw,source_sha256=excluded.source_sha256,'
                       'desired_job=excluded.desired_job',
                       (document.document_id,document.raw,document.source_sha256,job_id))
            return job_id

    def claim(self, job_id, lease_seconds):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job=db.execute('SELECT * FROM jobs WHERE job_id=?',(job_id,)).fetchone()
            if job['state']=='done' or (job['state']=='running' and job['expires']>time.time()):
                return None
            token=uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running',token=?,expires=? WHERE job_id=?",
                       (token,time.time()+lease_seconds,job_id))
            return dict(job,token=token)

    def finish(self, job, result):
        from .config import Settings
        settings=Settings(**json.loads(job['settings']))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active=db.execute('SELECT state,token FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()
            if active['state']!='running' or active['token']!=job['token']:
                return None
            next_id=db.execute('SELECT COALESCE(MAX(attempt_id),0)+1 FROM attempts').fetchone()[0]
            record=dict(result,attempt_id=next_id,source_generation=job['job_id'],
                        settings_fingerprint=settings.fingerprint,policy_version=settings.policy_version,
                        producing_settings=settings.public())
            if record['error']:
                record['error']['retry_command']=('python -m access_requests --db '+shlex.quote(str(self.path.resolve()))
                    +' --provider '+shlex.quote(settings.provider)+' retry '+shlex.quote(job['document_id']))
            db.execute('INSERT INTO attempts VALUES (?,?,?,?)',
                       (next_id,job['document_id'],job['source_sha256'],json.dumps(record)))
            db.execute('UPDATE documents SET current_attempt=? WHERE document_id=? AND desired_job=?',
                       (next_id,job['document_id'],job['job_id']))
            db.execute("UPDATE jobs SET state='done',token=NULL,expires=NULL WHERE job_id=?",(job['job_id'],))
            db.execute("UPDATE metadata SET value=value+1 WHERE key='version'")
            return record

    def pending(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT job_id,document_id,source_sha256,fingerprint,state,expires "
                                                  "FROM jobs WHERE state!='done' ORDER BY job_id")]

    def job_result(self, job_id):
        with self.connect() as db:
            row=db.execute("SELECT record FROM attempts WHERE json_extract(record,'$.source_generation')=?",(job_id,)).fetchone()
        return json.loads(row[0]) if row else None


    def inspect(self, history=False, document_id=None):
        """Read terminal and unfinished views in one SQLite snapshot."""
        with self.connect() as db:
            db.execute('BEGIN')
            if history:
                rows=db.execute('SELECT record FROM attempts WHERE (? IS NULL OR document_id=?) ORDER BY attempt_id',
                                (document_id,document_id))
                completed=[json.loads(r[0]) for r in rows]
            else:
                completed=self._current(db)
            pending=[dict(row) for row in db.execute("SELECT job_id,document_id,source_sha256,fingerprint,state,expires "
                "FROM jobs WHERE state!='done' AND (? IS NULL OR document_id=?) ORDER BY job_id",(document_id,document_id))]
            return dict(completed=completed,pending=pending)
