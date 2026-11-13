"""Bounded workers sharing brief SQLite claims, with calls outside transactions."""
from concurrent.futures import ThreadPoolExecutor
import time
from .intake import process_response


def run_attempt(store, attempt, provider_factory, *, max_retries=2, sleep=time.sleep):
    if not 0 <= max_retries <= 5:
        raise ValueError('max_retries must be between 0 and 5')
    config, _ = store.settings(attempt)
    lease = float(config.get('timeout', 30)) * (max_retries + 1) + 2 ** (max_retries + 1) + 30
    token = store.claim(attempt, lease_seconds=lease)
    if not token:
        return store.result(attempt)
    source = store.source_for(attempt)
    try:
        provider = provider_factory(source)
        for index in range(max_retries + 1):
            reply = provider.extract(source.message)
            if not reply.get('retryable') or index == max_retries:
                break
            sleep(2 ** index)
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
