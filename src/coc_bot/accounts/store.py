"""No login secrets are stored here. Registry changes are atomic and fail closed."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import os
import threading
import uuid

ROLES = ('donating', 'farming', 'upgrading', 'builder_base')
TAG = re.compile(r'^#[0289PYLQGRJCUV]{5,15}$')
IDENT = re.compile(r'^[a-f0-9]{32}$')
selected_account = ContextVar('selected_account', default=None)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read(path, default=None):
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, OSError) as exc:
        raise ValueError('Account data is unreadable; restore its backup before continuing') from exc


def tag(value):
    if not isinstance(value, str) or not TAG.fullmatch(value):
        raise ValueError('A verified Clash player tag is required')
    return value


def roles(value):
    if not isinstance(value, list) or any(type(x) is not str or x not in ROLES for x in value):
        raise ValueError('Choose listed account roles')
    return sorted(set(value))


def backup(root):
    """Checksum-verified settings/calibration/transaction snapshot; no screenshots."""
    root = Path(root).resolve()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = root/'data/account_backups'/stamp
    destination.mkdir(parents=True)
    manifest = {}
    for name in ('calibrated.yaml', 'user_settings.yaml', 'runtime_state.json', 'account.json',
                 'templates', 'icons', 'attack-planner', 'upgrades', 'builder_base', 'accounts/registry.json',
                 'progression/army.json', 'progression/picker-references', 'progression/army-references'):
        source = root/'data'/name
        if not source.exists():
            continue
        files = list(source.rglob('*')) if source.is_dir() else [source]
        if source.is_symlink() or any(p.is_symlink() for p in files):
            raise ValueError('Account backup refuses symbolic links')
        for path in files:
            if not path.is_file():
                continue
            relative = path.relative_to(root/'data')
            target = destination/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError('Account backup checksum failed')
            manifest[str(relative)] = digest
    write(destination/'manifest.json', manifest)
    return destination


class AccountStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root/'data/accounts/registry.json'
        self.lock = threading.RLock()

    def load(self):
        state = read(self.path, {'version': 1, 'active': None, 'accounts': [], 'pending': None})
        if state.get('version') != 1 or not isinstance(state.get('accounts'), list):
            raise ValueError('Unsupported account registry')
        ids = set()
        tags = set()
        for account in state['accounts']:
            if not isinstance(account, dict) or not IDENT.fullmatch(account.get('id', '')):
                raise ValueError('Invalid account registry entry')
            tag(account.get('tag'))
            roles(account.get('roles'))
            if type(account.get('original')) is not bool:
                raise ValueError('Invalid original account marker')
            if account['id'] in ids or account['tag'] in tags:
                raise ValueError('Duplicate account registry entry')
            ids.add(account['id']); tags.add(account['tag'])
        if state.get('active') is not None and state['active'] not in ids:
            raise ValueError('Active account is missing')
        if state['accounts'] and (state.get('active') is None or sum(a['original'] for a in state['accounts']) != 1):
            raise ValueError('Account registry must retain one original profile and an active account')
        return state

    @contextmanager
    def scope(self):
        from coc_bot.config import profile_root
        account = self.account()
        token = profile_root.set(self.profile(account))
        identity = selected_account.set(account)
        try:
            yield
        finally:
            selected_account.reset(identity)
            profile_root.reset(token)

    def account(self, ident=None):
        state = self.load()
        ident = ident or state['active']
        return next((a for a in state['accounts'] if a['id'] == ident), None)

    def profile(self, account=None):
        account = account or self.account()
        if account is None or account.get('original') is True:
            return self.root
        if not IDENT.fullmatch(account['id']):
            raise ValueError('Invalid account profile')
        path = self.root/'data/accounts/profiles'/account['id']
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError('Account profile is outside its installation')
        return path

    def require_ready(self, role=None):
        state = self.load()
        if state.get('pending'):
            raise ValueError('Finish account setup or verify the current account before starting automation')
        account = self.account()
        scoped = selected_account.get()
        if scoped and account and scoped['id'] != account['id']:
            raise ValueError('Selected account changed; reload this page before continuing')
        if account and role and role not in account['roles']:
            raise ValueError(f'This account does not have the {role.replace("_", " ")} role')
        return account

    def begin(self, kind, target=None):
        with self.lock:
            state = self.load()
            if state.get('pending'):
                raise ValueError('An account operation is unfinished; verify the current account first')
            if kind not in ('add', 'switch') or (kind == 'switch' and target not in {a['id'] for a in state['accounts']}):
                raise ValueError('Invalid account operation')
            state['pending'] = {'kind': kind, 'target': target, 'previous': state['active']}
            write(self.path, state)

    def register(self, identity, nickname, selected_roles):
        player_tag = tag(identity['tag'])
        selected_roles = roles(selected_roles)
        nickname = nickname.strip()
        if not nickname or len(nickname) > 60 or any(ord(c) < 32 for c in nickname):
            raise ValueError('Use a nickname of 1–60 characters')
        with self.lock:
            state = self.load()
            existing = next((a for a in state['accounts'] if a['tag'] == player_tag), None)
            if existing:
                # Registering a remembered identity must not overwrite its settings/roles.
                return self.complete(player_tag)
            if (state.get('pending') or {}).get('target'):
                raise ValueError('Unexpected account loaded during a switch')
            first = not state['accounts']
            backup_path = backup(self.root)
            account = {'id': uuid.uuid4().hex, 'tag': player_tag, 'nickname': nickname,
                       'selector': identity.get('selector', ''),
                       'game_name': identity.get('name', ''), 'roles': selected_roles,
                       'original': first, 'backup': str(backup_path.relative_to(self.root))}
            destination = self.profile(account)
            if not first:
                destination.mkdir(parents=True, exist_ok=False)
                shutil.copytree(self.root/'config', destination/'config')
                for name in ('calibrated.yaml', 'templates', 'icons', 'game', 'live'):
                    source = self.root/'data'/name
                    if not source.exists():
                        continue
                    if source.is_symlink() or source.is_dir() and any(p.is_symlink() for p in source.rglob('*')):
                        raise ValueError('Account initialization refuses symbolic links')
                    target = destination/'data'/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_dir(): shutil.copytree(source, target)
                    else: shutil.copy2(source, target)
                # Device recognition can be reused; another army's saved taps cannot.
                import yaml
                calibration = destination/'data/calibrated.yaml'
                if calibration.exists():
                    data = yaml.safe_load(calibration.read_text()) or {}
                    data.pop('farm_deploy_sequence', None)
                    calibration.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
                # Copy the device connection, not balances, schedules or upgrade decisions.
                settings = self.root/'data/user_settings.yaml'
                original = yaml.safe_load(settings.read_text(encoding='utf-8')) if settings.exists() else {}
                shared = {k: v for k, v in (original or {}).items() if k in ('adb', 'gui')}
                shared['farm'] = {'enabled': False, 'engine': 'automatic'}
                (destination/'data/user_settings.yaml').write_text(yaml.safe_dump(shared), encoding='utf-8')
            state['accounts'].append(account)
            state['active'] = account['id']; state['pending'] = None
            write(self.path, state)
            return account

    def update(self, ident, nickname, selected_roles):
        selected_roles = roles(selected_roles)
        nickname = nickname.strip()
        if not nickname or len(nickname) > 60 or any(ord(c) < 32 for c in nickname):
            raise ValueError('Use a nickname of 1–60 characters')
        with self.lock:
            state = self.load()
            account = next((a for a in state['accounts'] if a['id'] == ident), None)
            if account is None: raise ValueError('Unknown account')
            account.update(nickname=nickname, roles=selected_roles)
            write(self.path, state)

    def complete(self, player_tag):
        with self.lock:
            state = self.load()
            account = next((a for a in state['accounts'] if a['tag'] == tag(player_tag)), None)
            if not account:
                raise ValueError('This village is not saved yet. Choose its tasks and press Save and verify account in Accounts.')
            target = (state.get('pending') or {}).get('target')
            if target and target != account['id']:
                raise ValueError('A different account loaded; automation remains paused')
            state['active'] = account['id']; state['pending'] = None
            write(self.path, state)
            return account


def apply_roles(config, account):
    from dataclasses import replace
    if account is None:
        return config
    selected = set(roles(account['roles']))
    return replace(config,
        account_tag=account['tag'], account_roles=tuple(selected),
        donation_enabled='donating' in selected,
        farm_enabled=config.farm_enabled and 'farming' in selected,
        upgrade_buildings_enabled=config.upgrade_buildings_enabled and 'upgrading' in selected,
        upgrade_research_enabled=config.upgrade_research_enabled and 'upgrading' in selected,
        upgrade_pets_enabled=config.upgrade_pets_enabled and 'upgrading' in selected,
        builder_base_attacks_enabled=config.builder_base_attacks_enabled and 'builder_base' in selected,
        builder_base_upgrades_enabled=config.builder_base_upgrades_enabled and 'builder_base' in selected,
        builder_base_research_enabled=config.builder_base_research_enabled and 'builder_base' in selected,
        builder_base_collect_resources=config.builder_base_collect_resources and 'builder_base' in selected)
