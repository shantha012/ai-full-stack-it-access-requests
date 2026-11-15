from .intake import read_document
from .pipeline import process

class Engine:
    def __init__(self, store):
        self.store = store

    def intake(self, paths, provider):
        results=[]
        for path in paths:
            document=read_document(path)
            results.append(self.store.save(document,process(document,provider)))
        return results
