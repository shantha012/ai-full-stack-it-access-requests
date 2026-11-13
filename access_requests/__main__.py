"""Command line interface for a shared local intake database."""
import argparse
import json
from pathlib import Path

from .providers import MockProvider, HTTPProvider
from .sources import load_source
from .storage import Store
from .workers import intake, run_attempt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('intake', 'queue', 'history', 'retry', 'resume', 'export'):
        sub = commands.add_parser(command)
        sub.add_argument('--db', default='access-requests.sqlite')
        if command == 'intake':
            sub.add_argument('inputs', nargs='+')
            sub.add_argument('--workers', type=int, default=4)
            sub.add_argument('--mocks', default='tests/mock_responses')
            sub.add_argument('--provider', choices=('mock', 'http'), default='mock')
            sub.add_argument('--endpoint', default='https://api.openai.com/v1/chat/completions')
            sub.add_argument('--model', default='gpt-4o-mini')
            sub.add_argument('--timeout', type=float, default=30)
        if command == 'export':
            sub.add_argument('--output', default='deliverables')
        if command in ('history', 'retry'):
            sub.add_argument('--document', required=True)
    args = parser.parse_args(argv)
    store = Store(args.db)
    if args.command == 'queue':
        result = store.queue()
    elif args.command == 'history':
        result = store.history(args.document)
    elif args.command == 'export':
        from .exports import export_current
        result = export_current(store, args.output)
    elif args.command in ('retry', 'resume'):
        def saved_factory(source, config):
            if config.get('provider') == 'http':
                return HTTPProvider(endpoint=config['endpoint'], model=config['model'], timeout=config['timeout'])
            return MockProvider(Path(config.get('mocks', 'tests/mock_responses')) / (Path(source.document_id).stem + '-success.json'))
        if args.command == 'retry':
            rows = store.history(args.document)
            if not rows:
                parser.error('unknown document')
            previous = rows[-1]['attempt_id']
            config, policy = store.settings(previous)
            attempt = store.enqueue(store.source_for(previous), config=config, policy=policy, force=True)
            result = run_attempt(store, attempt, lambda source: saved_factory(source, config))
        else:
            store.recover()
            for row in store.queue():
                if row['state'] == 'pending':
                    config, _ = store.settings(row['attempt_id'])
                    run_attempt(store, row['attempt_id'], lambda source: saved_factory(source, config))
            result = store.queue()
    else:
        paths = []
        for path in map(Path, args.inputs):
            paths.extend(sorted(path.glob('*.json')) if path.is_dir() else [path])
        if args.provider == 'mock':
            config = dict(provider='mock', mocks=str(Path(args.mocks).resolve()))
            factory = lambda source: MockProvider(Path(config['mocks']) / (Path(source.document_id).stem + '-success.json'))
        else:
            config = dict(provider='http', endpoint=args.endpoint, model=args.model, timeout=args.timeout)
            factory = lambda source: HTTPProvider(endpoint=args.endpoint, model=args.model, timeout=args.timeout)
        result = intake(store, [load_source(path) for path in paths], factory,
                        workers=args.workers, config=config)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
