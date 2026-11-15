from .intake import read_document
from .pipeline import process

class Engine:
    def __init__(self, store):
        self.store = store

    def run(self, document, provider, force=False):
        cached=None if force else self.store.reusable(document)
        return cached or self.store.save(document,process(document,provider))

    def intake(self, paths, provider):
        return [self.run(read_document(path),provider) for path in paths]

    def retry(self, document_id, provider):
        return self.run(self.store.document(document_id),provider,force=True)
