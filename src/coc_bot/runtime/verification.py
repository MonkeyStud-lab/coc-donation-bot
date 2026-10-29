"""Bounded, account-local records of checks that could not prove an action."""
import hashlib
import json
import time
import math

from loguru import logger
from coc_bot.upgrades.runner import write_json

LIMIT = 100


def timestamp(value,default):
    return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else default


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def record_failure(config, feature, message, *, pending=None, evidence=None):
    """Keep receipts intact; repeated observations update one bounded record."""
    path = config.data_dir / 'verification/failures.json'
    now = time.time()
    identity = fingerprint([feature, message, pending])[:16]
    try:
        records = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        if not isinstance(records, list):
            records = []
    except (OSError, ValueError):
        records = []
    previous = next((v for v in records if isinstance(v, dict) and v.get('id') == identity), {})
    entry = dict(previous, id=identity, feature=feature, message=message,
                 account=getattr(config, 'account_tag', None),
                 first_seen=timestamp(previous.get('first_seen'),now), last_seen=now,
                 count=min(previous['count'],10**9)+1 if type(previous.get('count')) is int and previous['count']>=0 else 1,
                 status='needs_review')
    entry.pop('resolved_at',None)
    if pending is not None:
        entry['receipt'] = pending
    if evidence is not None:
        entry['evidence'] = str(evidence)
    last_warning=timestamp(previous.get('last_warning'),0)
    announce = now-last_warning>=60 or last_warning>now
    if not announce:entry['last_warning']=last_warning
    if announce:
        entry['last_warning'] = now
    records = [v for v in records if isinstance(v, dict) and v.get('id') != identity]
    records.append(entry)
    try:
        write_json(path, records[-LIMIT:])
    except OSError as exc:
        logger.warning('Verification failure log could not be saved: {}', exc)
    if announce:
        logger.warning('Verification failed [{}] {}: {}. Affected action paused; receipt retained. Log: {}',
                       identity, feature, message, path)
    return identity


def log_result(config, feature, result, *, pending=None):
    if result.get('status') in ('needs_review', 'blocked', 'changed'):
        return record_failure(config, feature, result.get('message') or result['status'],
                              pending=pending if isinstance(pending,dict) else None)
    return None


def resolve_receipt(config, receipt):
    """Independent proof can resolve a recorded failure without deleting history."""
    path=config.data_dir/'verification/failures.json'
    if not path.exists():return
    try:
        records=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(records,list):return
        changed=False
        for entry in records:
            if (isinstance(entry,dict) and entry.get('receipt')==receipt
                and entry.get('status')=='needs_review'):
                entry.update(status='resolved',resolved_at=time.time());changed=True
        if changed:write_json(path,records[-LIMIT:])
    except (OSError,ValueError) as exc:
        logger.warning('Verification resolution log could not be saved: {}',exc)
