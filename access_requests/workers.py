"""Bounded workers sharing brief SQLite claims, with calls outside transactions."""
from concurrent.futures import ThreadPoolExecutor
from .intake import process_response


def run_attempt(store, attempt, provider_factory):
    token = store.claim(attempt)
    if not token:
        return store.result(attempt)
    source = store.source_for(attempt)
    try:
        reply = provider_factory(source).extract(source.message)
    except Exception:
        reply = {'response_source': 'unknown', 'error': 'Provider adapter failed'}
    store.publish(attempt, token, process_response(source, reply))
    return store.result(attempt)


def intake(store, sources, provider_factory, *, workers=4, config=None):
    if not 1 <= workers <= 32:
        raise ValueError('workers must be between 1 and 32')
    attempts = [store.enqueue(source, config=config) for source in sources]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda attempt: run_attempt(store, attempt, provider_factory), attempts))
