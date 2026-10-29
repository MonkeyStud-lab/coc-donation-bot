"""Bound generated attack diagnostics; never touch calibration or training data.

Call only between operations while owning DeviceLease. Diagnostic write failures
must not prevent Stop or game recovery. Unknown files and symlinks are excluded.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import time

from loguru import logger

UUID = re.compile(r'^[a-f0-9]{32}$')
EXECUTION = re.compile(r'^([a-f0-9]{32})(?:\.jsonl|\.(?:before|after|blocked|selection|failed)\.png)$')


@dataclass(frozen=True)
class RetentionPolicy:
    days: int = 7
    max_bytes: int = 1024**3
    max_groups: int = 40
    keep_recent: int = 3  # per family, even when older than days


def prune_attack_diagnostics(data_dir, *, policy=RetentionPolicy(), now=None, dry_run=False):
    """Prune oldest whole evidence groups, preserving each family's newest three.

    The byte/count caps are soft when the protected newest evidence alone exceeds
    them. Pending recovery disables cleanup entirely, including corrupt markers.
    """
    root = Path(data_dir)
    # Do not follow a replaced root/debug or family directory outside the profile.
    debug = root/'debug'
    builder_marker = root/'builder_base/visit.json'
    builder_pending = False
    if builder_marker.exists():
        try:
            import json
            builder_pending = bool(json.loads(builder_marker.read_text(encoding='utf-8')).get('phase'))
        except (OSError, ValueError, AttributeError):
            builder_pending = True
    if (root.is_symlink() or debug.is_symlink() or
            builder_pending or
            (root/'attack-planner/attack-pending.json').exists() or
            (root/'attack-planner/camera-pending.json').exists()):
        return {'removed_groups': 0, 'removed_bytes': 0, 'skipped_pending': True}
    now = time.time() if now is None else now
    groups = []
    try:
        for family in ('attack-surveys', 'attack-v2', 'attack-executions', 'builder-base'):
            folder = debug/family
            if folder.is_symlink() or not folder.is_dir():
                continue
            if family == 'attack-executions':
                by_id = {}
                for path in folder.iterdir():
                    match = EXECUTION.fullmatch(path.name)
                    if match and path.is_file() and not path.is_symlink():
                        by_id.setdefault(match[1], []).append(path)
                items = [(None, paths) for paths in by_id.values()]
            else:
                items = []
                for directory in folder.iterdir():
                    if not UUID.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir():
                        continue
                    children = list(directory.iterdir())
                    # Only flat generated reports; never recurse into an
                    # unexpected directory, junction, symlink or retained copy.
                    pattern = (r'\d{3}-(?:boat-not-found|battle-results|stage-view|unsupported-army|deployment-confirmed|verification-failed|slot-\d+-attempt-\d+)\.png'
                               if family == 'builder-base' else
                               r'(?:reference|before|after|mosaic|overlay|view-\d+)\.(?:png|json)|camera\.json')
                    if all(p.is_file() and not p.is_symlink() and
                           re.fullmatch(pattern, p.name)
                           for p in children):
                        items.append((directory, children))
            for directory, paths in items:
                if not paths:
                    continue
                stats = [p.stat() for p in paths]
                groups.append(dict(family=family, directory=directory, paths=paths,
                                   at=max(s.st_mtime for s in stats), size=sum(s.st_size for s in stats)))
        protected = set()
        for family in {g['family'] for g in groups}:
            recent = sorted((g for g in groups if g['family'] == family), key=lambda g: g['at'], reverse=True)
            protected.update(id(g) for g in recent[:policy.keep_recent])
        total = sum(g['size'] for g in groups)
        count = len(groups)
        removed = size = 0
        for group in sorted(groups, key=lambda g: g['at']):
            if id(group) in protected:
                continue
            if (group['at'] >= now-policy.days*86400 and total <= policy.max_bytes and count <= policy.max_groups):
                continue
            if not dry_run:
                for path in group['paths']:
                    path.unlink()
                if group['directory'] is not None:
                    group['directory'].rmdir()
            removed += 1
            size += group['size']
            total -= group['size']
            count -= 1
        result = dict(removed_groups=removed, removed_bytes=size, remaining_bytes=total,
                      remaining_groups=count, over_budget=total > policy.max_bytes or count > policy.max_groups)
        if removed:
            logger.info('Attack screenshot retention{}: {} groups, {:.1f} MiB {}',
                        ' preview' if dry_run else '', removed, size/1024**2, 'eligible' if dry_run else 'removed')
        if result['over_budget']:
            logger.warning('Newest protected attack evidence exceeds retention budget; preserved for diagnosis')
        return result
    except OSError as exc:
        logger.warning('Attack screenshot cleanup deferred: {}', exc)
        return {'removed_groups': 0, 'removed_bytes': 0, 'error': str(exc)}
