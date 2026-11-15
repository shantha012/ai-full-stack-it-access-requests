import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from support import OfflineTest, ROOT, MOCKS, reply

class T28(OfflineTest):
    def test_frozen_install_and_exact_documented_walkthrough(self):
        self.assertTrue((ROOT/'deliverables').is_dir())
        self.assertFalse((ROOT/'deliverables').is_symlink())
        readme=(ROOT/'README.md').read_text()
        match=re.search(r'<!-- offline-walkthrough -->\s*```bash\n(.*?)```',readme,re.S)
        self.assertIsNotNone(match,'README must contain the exact mock walkthrough')
        for name in ('uv.lock','pyproject.toml','reports/verification.md','reports/accuracy.md','reports/request-evidence.json'):
            self.assertTrue((ROOT/name).is_file(),name)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('access_requests','materials','test','tests/fixtures','reports'):
                shutil.copytree(ROOT/name,root/name)
            for name in ('pyproject.toml','uv.lock','snapshot.schema.json'):
                shutil.copy2(ROOT/name,root/name)
            environment=dict(os.environ,UV_CACHE_DIR='/tmp/access-uv-cache',UV_PYTHON_DOWNLOADS='never')
            install=subprocess.run(['uv','sync','--frozen','--offline'],cwd=root,env=environment,text=True,capture_output=True)
            self.assertEqual(install.returncode,0,install.stderr)
            environment['PATH']=str(root/'.venv/bin')+os.pathsep+environment['PATH']
            walkthrough=subprocess.run(['bash','-eu','-c',match[1]],cwd=root,env=environment,text=True,capture_output=True,timeout=60)
            self.assertEqual(walkthrough.returncode,0,walkthrough.stderr)
            from access_requests.storage import Store
            store=Store(root/'state/access.sqlite')
            current={r['document_id']:r for r in store.current()}
            self.assertEqual(len(current),20)
            self.assertEqual((current['IT-001.json']['status'],current['IT-001.json']['owner'],current['IT-001.json']['next_action']),('review','System Owner','review-request'))
            self.assertEqual(current['IT-010.json']['next_action'],'clarify')
            self.assertTrue(any(r['status']=='error' for r in store.attempts('IT-001.json')))
            self.assertIn('retry-extraction',walkthrough.stdout)
            self.assertIn('needs-information',walkthrough.stdout)
            self.assertEqual(store.pending(),[])
            resolved=(root/'state/deliverables').resolve()
            for name in ('extractions.jsonl','queue.json','accuracy.md','request-evidence.json','verification.md'):
                self.assertTrue((resolved/name).is_file(),name)
            rows=[json.loads(line) for line in (resolved/'extractions.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),20)
            measured=json.loads((root/'state/accuracy.json').read_text())
            self.assertEqual(measured['denominator'],252)
            self.assertEqual(measured['missing_or_failed_cells'],0)

class T29(OfflineTest):
    def test_2000_messages_two_processes_bounded_workers_and_progress(self):
        template=reply('load-complete')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); sources=root/'input'; sources.mkdir()
            saved=root/'test/mock_responses'; saved.mkdir(parents=True)
            bundle={}
            for n in range(1001,3001):
                name=f'IT-{n}.json'
                text=('Request IT-'+str(n)+', dated 2026-10-22. This is a new request. Requester: Maya Chen. '
                      'Team: Analytics. System: Atlas. Environment: staging. Requested permission: read. '
                      'Business purpose: checking dashboard totals. Start date: 2026-10-23. End date: 2026-11-06. Manager: Priya Shah.')
                (sources/name).write_text(json.dumps({'message':text}))
                bundle[name]=json.loads(json.dumps(template).replace('{n}',str(n)))
            (saved/'corpus-replies.json').write_text(json.dumps(bundle))
            code='''
import sys,threading,json
from access_requests.engine import Engine
from access_requests.storage import Store
from access_requests.provider import CorpusProvider
from pathlib import Path
active=maximum=0
lock=threading.Lock()
class Bounded(CorpusProvider):
 def for_document(self,doc):
  selected=super().for_document(doc)
  class Saved:
   response_source='mock'
   def extract(inner,message):
    global active,maximum
    with lock:
     active+=1;maximum=max(maximum,active)
    try:
     if doc=='IT-1001.json':
      print('BLOCKED',flush=True);sys.stdin.readline()
     return selected.extract(message)
    finally:
     with lock: active-=1
  return Saved()
Engine(Store(sys.argv[1]),workers=4,lease_seconds=3600).intake(sorted(Path(sys.argv[2]).glob('*.json')),Bounded(sys.argv[3]))
print('MAX='+str(maximum),flush=True)
'''
            db=root/'state.sqlite'
            start=time.monotonic()
            first=subprocess.Popen([sys.executable,'-c',code,str(db),str(sources),str(saved)],cwd=ROOT,
                                   stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            self.addCleanup(lambda: first.poll() is None and first.kill())
            try:
                self.assertEqual(first.stdout.readline().strip(),'BLOCKED')
                second=subprocess.run([sys.executable,'-m','access_requests','--db',str(db),'--provider','mock',
                    '--mock-dir',str(saved),'--workers','4','intake',str(sources)],cwd=ROOT,
                    stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=120)
                self.assertEqual(second.returncode,0,second.stderr)
                from access_requests.storage import Store
                store=Store(db)
                current=store.current()
                self.assertEqual(len(current),1999)
                self.assertEqual(store.pending()[0]['document_id'],'IT-1001.json')
                first.stdin.write('\n');first.stdin.flush()
                remaining=first.communicate(timeout=120)[0]
                self.assertEqual(first.returncode,0)
                self.assertLessEqual(int(remaining.strip().split('MAX=')[-1]),4)
                records=store.current()
                self.assertEqual(len(records),2000)
                self.assertEqual(len(store.attempts()),2000)
                for record in records:
                    self.assertEqual(record['owner'],'System Owner')
                    self.assertEqual(record['extraction']['request_id'],record['document_id'][:-5])
                print(f'T29 observed: 2000 mock documents, two processes, workers <=4, {time.monotonic()-start:.2f}s',flush=True)
            finally:
                if first.poll() is None: first.kill();first.wait()
                if first.stdin and not first.stdin.closed: first.stdin.close()
                if first.stdout: first.stdout.close()
