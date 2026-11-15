"""Bounded scheduling; SQLite transactions never span a provider invocation."""
from concurrent.futures import ThreadPoolExecutor
import json
from .config import Settings
from .intake import read_document, Document
from .pipeline import process

class Engine:
    def __init__(self, store, settings=None, workers=1, lease_seconds=None):
        self.store = store
        self.settings = settings or Settings()
        self.workers=max(1,min(workers,32))
        self.lease_seconds=lease_seconds if lease_seconds is not None else self.settings.timeout+30

    def execute(self, job_id, provider):
        job=self.store.claim(job_id,self.lease_seconds)
        if job is None:
            return self.store.job_result(job_id)
        settings=Settings(**json.loads(job['settings']))
        document=Document(job['document_id'],job['source_sha256'],json.loads(job['raw'])['message'],job['raw'])
        selected=provider.for_document(document.document_id) if hasattr(provider,'for_document') else provider
        result=process(document,selected,settings)
        return self.store.finish(job,result)

    def run(self, document, provider, force=False):
        return self.execute(self.store.register(document,self.settings,force),provider)

    def intake(self, paths, provider):
        jobs=[self.store.register(read_document(path),self.settings) for path in paths]
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(lambda job: self.execute(job,provider),jobs))

    def retry(self, document_id, provider):
        return self.run(self.store.document(document_id),provider,force=True)

    def refresh(self, document_id, provider):
        return self.retry(document_id,provider)

    def resume(self, provider):
        jobs=[job['job_id'] for job in self.store.pending()]
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(lambda job: self.execute(job,provider),jobs))
