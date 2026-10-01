"""Explicit read-only OpenD diagnostic. Contains no trading side effects."""
import argparse
import json
from pathlib import Path

from moomoo_component.brokers import MoomooBroker


parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=18441)
parser.add_argument('--firm', default='FUTUSECURITIES')
parser.add_argument('--account-id', default=None, help='Optional SIMULATE account for read-only snapshot')
parser.add_argument('--snapshot', action='store_true', help='Read snapshot if exactly one eligible simulation account is found; no order')
parser.add_argument('--report', type=Path)
args = parser.parse_args()
broker = MoomooBroker(port=args.port, security_firm=args.firm, account_id=args.account_id)
try:
    info = broker.probe()
    report = {**info, 'accounts': [{**a, 'account_id': '****' + a['account_id'][-4:]} for a in info['accounts']]}
    if args.snapshot and not args.account_id:
        if len(info['accounts']) != 1:
            raise ValueError('需要明确指定一个模拟账户才能检查快照')
        broker.account_id = info['accounts'][0]['account_id']
        args.account_id = broker.account_id
    if args.account_id:
        try:
            snap = broker.snapshot(['US.AAPL'])
            report['snapshot'] = dict(validated=True, quote=snap['quotes']['US.AAPL'], positions_count=len(snap['positions']), open_orders_count=len(snap['open_orders']), funds_validated=True, funds_source=snap.get('funds_source'), positive_cash=snap['cash'] > 0)
        except Exception as exc:
            report['snapshot'] = dict(validated=False, error=str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
finally:
    broker.close()
