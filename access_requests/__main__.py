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
    args=parser.parse_args()
    store=Store(args.db)
    if args.command=='queue': result=store.current()
    elif args.command=='attempts': result=store.attempts(args.document_id)
    else: result=str(store.export(args.output))
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
