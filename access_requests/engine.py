from .intake import read_document
from .pipeline import process

class Engine:
    def __init__(self, store, settings=None):
        from .config import Settings
        self.settings = settings or Settings()
        self.store = store

    def run(self, document, provider, force=False):
        cached=None if force else self.store.reusable(document,self.settings)
        return cached or self.store.save(document,process(document,provider,self.settings),self.settings)

    def intake(self, paths, provider):
        return [self.run(read_document(path),provider) for path in paths]

    def retry(self, document_id, provider):
        return self.run(self.store.document(document_id),provider,force=True)

    def refresh(self, document_id, provider):
        return self.retry(document_id,provider)
