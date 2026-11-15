"""Human review queue CLI."""
import argparse
import json
from .storage import Store

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='state/access.sqlite')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('queue')
    attempts=sub.add_parser('attempts'); attempts.add_argument('document_id',nargs='?')
    export=sub.add_parser('export'); export.add_argument('--output',default='deliverables')
    accuracy=sub.add_parser('accuracy')
    accuracy.add_argument('--expectations',default='tests/fixtures/expectations.json')
    accuracy.add_argument('--extra-records')
    accuracy.add_argument('--output')
    args=parser.parse_args()
    store=Store(args.db)
    if args.command=='queue': result=store.current()
    elif args.command=='attempts': result=store.attempts(args.document_id)
    elif args.command=='accuracy':
        from pathlib import Path
        from .accuracy import compare, render_report
        expected=json.loads(Path(args.expectations).read_text())
        records=store.current()
        if args.extra_records:
            records += [json.loads(line) for line in Path(args.extra_records).read_text().splitlines()]
        result=compare(records,expected)
        if args.output:
            Path(args.output).write_text(render_report(result,expected))
    else: result=str(store.export(args.output))
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
