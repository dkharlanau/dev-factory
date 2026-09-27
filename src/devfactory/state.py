"""SQLite is execution metadata only; repository/GitHub remain task authority."""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from .policy import Stop

TERMINAL = {'READY_LOCAL', 'PR_OPENED', 'PR_READY', 'IDLE', 'COMPLETED'}

def identity(pid):
    r = subprocess.run(['ps','-p',str(pid),'-o','lstart='],capture_output=True,text=True)
    return r.stdout.strip() if r.returncode == 0 else None

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp = path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    fd = os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(data,f,indent=2,sort_keys=True)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(temp,path)

class Store:
    def __init__(self, directory):
        self.path = Path(directory).resolve()
        self.path.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db = sqlite3.connect(self.path/'factory.sqlite3',timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, task_key TEXT NOT NULL, project TEXT NOT NULL,
          state TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS task_lookup ON runs(task_key);
        CREATE TABLE IF NOT EXISTS run_tasks (
          task_key TEXT PRIMARY KEY, run_id TEXT NOT NULL, task_id TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS run_task_id_lookup ON run_tasks(task_id);
        CREATE TABLE IF NOT EXISTS lease (
          slot INTEGER PRIMARY KEY CHECK(slot=1), run_id TEXT NOT NULL,
          task_key TEXT NOT NULL UNIQUE, pid INTEGER NOT NULL, identity TEXT,
          worktree TEXT, heartbeat REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS control (run_id TEXT PRIMARY KEY, pause INTEGER NOT NULL DEFAULT 0);
        ''')
        os.chmod(self.path/'factory.sqlite3',0o600)
        self.lock = None

    def close(self):
        self.release_lock(); self.db.close()

    def acquire_lock(self):
        if self.lock is not None: return
        handle = open(self.path/'worker.lock','a+')
        try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close(); raise Stop('BUSY','A Factory worker already holds the global local lock')
        self.lock = handle

    def release_lock(self):
        if self.lock:
            fcntl.flock(self.lock,fcntl.LOCK_UN); self.lock.close(); self.lock=None

    def create(self, project, task_key, data, aliases=None):
        rid=uuid.uuid4().hex[:16]; now=time.time()
        aliases=aliases or [(task_key,data.get('task_id') or task_key)]
        with self.db:
            self.db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',
                            (rid,task_key,project,'CLAIMED',json.dumps(data),now,now))
            self.db.executemany('INSERT INTO run_tasks(task_key,run_id,task_id) VALUES(?,?,?)',
                                [(key,rid,task_id) for key,task_id in aliases])
        return rid

    def get(self, rid):
        r=self.db.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        if r is None: raise Stop('NOT_FOUND','Unknown Factory run: '+rid)
        result=dict(r); result['data']=json.loads(result['data']); return result

    def all(self):
        return [self.get(r[0]) for r in self.db.execute('SELECT id FROM runs ORDER BY created DESC')]

    def existing(self, task_key):
        r=self.db.execute('SELECT run_id FROM run_tasks WHERE task_key=?',(task_key,)).fetchone()
        if r: return self.get(r[0])
        r=self.db.execute('SELECT id FROM runs WHERE task_key=? ORDER BY created DESC LIMIT 1',(task_key,)).fetchone()
        return self.get(r[0]) if r else None

    def by_task(self, project, task_id):
        r=self.db.execute('''SELECT rt.run_id FROM run_tasks rt JOIN runs r ON r.id=rt.run_id
                             WHERE r.project=? AND rt.task_id=? ORDER BY r.created DESC LIMIT 1''',
                          (project,task_id)).fetchone()
        if r: return self.get(r[0])
        for run in self.all():
            if run['project']==project and run['data'].get('task_id')==task_id: return run
        return None

    def claim(self, rid, *, recovering=False):
        self.acquire_lock(); run=self.get(rid)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT * FROM lease WHERE slot=1').fetchone()
            if old:
                live=identity(old['pid'])
                if live and live==old['identity']:
                    raise Stop('BUSY','Lease belongs to a live process; TTL does not authorize stealing')
                if old['run_id']!=rid or not recovering:
                    raise Stop('RECOVERY_REQUIRED','Resume abandoned run '+old['run_id']+' before starting new work')
                self.db.execute('DELETE FROM lease WHERE slot=1')
            self.db.execute('INSERT INTO lease VALUES(1,?,?,?,?,?,?)',
                            (rid,run['task_key'],os.getpid(),identity(os.getpid()),run['data'].get('worktree'),time.time()))
            self.db.execute('INSERT OR REPLACE INTO control VALUES(?,0)',(rid,))

    def heartbeat(self, rid, worktree=None):
        with self.db:
            self.db.execute('UPDATE lease SET heartbeat=?,worktree=COALESCE(?,worktree) WHERE run_id=?',
                            (time.time(),str(worktree) if worktree else None,rid))

    def save(self, rid, state, data):
        with self.db:
            self.db.execute('UPDATE runs SET state=?,data=?,updated=? WHERE id=?',
                            (state,json.dumps(data),time.time(),rid))
        atomic_json(self.path/'runs'/rid/'receipt.json',self.get(rid))

    def release(self, rid):
        with self.db:
            self.db.execute('DELETE FROM lease WHERE run_id=? AND pid=? AND identity=?',
                            (rid,os.getpid(),identity(os.getpid())))
        self.release_lock()

    def pause(self, rid):
        run=self.get(rid)
        if run['state'] in TERMINAL: return run
        with self.db: self.db.execute('INSERT OR REPLACE INTO control VALUES(?,1)',(rid,))
        return self.get(rid)

    def paused(self, rid):
        row=self.db.execute('SELECT pause FROM control WHERE run_id=?',(rid,)).fetchone()
        return bool(row and row[0])
