"""Prepare access requests for human review; inspect and recover durable work."""
import argparse
import json
from pathlib import Path
from .config import Settings
from .engine import Engine
from .storage import Store
from .provider import CorpusProvider, MockProvider, ProviderError

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='state/access.sqlite')
    parser.add_argument('--provider',choices=('mock','openai'),default='mock')
    parser.add_argument('--mock-dir',default='test/mock_responses')
    parser.add_argument('--model',default=Settings.model)
    parser.add_argument('--endpoint',default=Settings.endpoint)
    parser.add_argument('--timeout',type=float,default=30)
    parser.add_argument('--max-output-tokens',type=int,default=2048)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--lease-seconds',type=float)
    parser.add_argument('--prompt-file')
    parser.add_argument('--schema-file')
    parser.add_argument('--policy-file')
    sub=parser.add_subparsers(dest='command',required=True)
    intake=sub.add_parser('intake'); intake.add_argument('paths',nargs='+')
    queue=sub.add_parser('queue'); queue.add_argument('--pending',action='store_true')
    attempts=sub.add_parser('attempts'); attempts.add_argument('document_id',nargs='?')
    attempts.add_argument('--pending',action='store_true')
    sub.add_parser('resume')
    for name in ('retry','refresh'):
        command=sub.add_parser(name); command.add_argument('document_id')
        command.add_argument('--mock-reply',help='explicit saved scripted reply basename')
    export=sub.add_parser('export'); export.add_argument('--output',default='state/deliverables')
    accuracy=sub.add_parser('accuracy')
    accuracy.add_argument('--expectations',default='tests/fixtures/expectations.json')
    accuracy.add_argument('--extra-records'); accuracy.add_argument('--output')
    args=parser.parse_args()
    if args.timeout<=0 or args.max_output_tokens<=0:
        parser.error('timeout and output budget must be positive')
    store=Store(args.db)
    if args.command=='queue':
        result=store.inspect() if args.pending else store.current()
    elif args.command=='attempts':
        result=store.inspect(history=True,document_id=args.document_id) if args.pending else store.attempts(args.document_id)
    elif args.command=='accuracy':
        from .accuracy import compare, render_report
        expected=json.loads(Path(args.expectations).read_text())
        records=store.current()
        if args.extra_records:
            records += [json.loads(line) for line in Path(args.extra_records).read_text().splitlines()]
        result=compare(records,expected)
        if args.output:
            Path(args.output).write_text(render_report(result,expected))
    elif args.command=='export': result=str(store.export(args.output))
    else:
        options=dict(provider=args.provider,model=args.model,endpoint=args.endpoint,
                     timeout=args.timeout,max_output_tokens=args.max_output_tokens)
        for flag,field in (('prompt_file','prompt'),('policy_file','policy'),('schema_file','schema')):
            if getattr(args,flag):
                text=Path(getattr(args,flag)).read_text()
                options[field]=json.loads(text) if field=='schema' else text
        settings=Settings(**options)
        if args.provider=='openai':
            from .http_provider import ResponsesProvider
            try: provider=ResponsesProvider(settings)
            except ProviderError as error: parser.error(str(error))
        elif getattr(args,'mock_reply',None): provider=MockProvider(args.mock_dir,[args.mock_reply])
        else: provider=CorpusProvider(args.mock_dir)
        engine=Engine(store,settings,workers=args.workers,lease_seconds=args.lease_seconds)
        if args.command=='intake':
            paths=[]
            for name in args.paths:
                path=Path(name)
                paths.extend(sorted(path.glob('*.json')) if path.is_dir() else [path])
            processed=engine.intake(paths,provider)
        elif args.command=='resume': processed=engine.resume(provider)
        else: processed=[getattr(engine,args.command)(args.document_id,provider)]
        result=dict(completed=sum(r is not None for r in processed),
                    errors=sum(r is not None and r['status']=='error' for r in processed),
                    pending=len(store.pending()))
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
