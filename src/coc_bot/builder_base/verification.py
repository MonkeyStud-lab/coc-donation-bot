"""A saved uncertain receipt may pause Builder actions after verified Home return."""
from coc_bot.accounts.store import read
from coc_bot.runtime.verification import fingerprint
import time


def deferred(config, journal=None):
    journal = read(config.data_dir/'builder_base/upgrades.json', {}) if journal is None else journal
    receipt = journal.get('pending')
    marker = journal.get('deferred_receipt', {})
    account = getattr(config, 'account_tag', None)
    return (isinstance(marker, dict) and isinstance(receipt, dict) and bool(receipt)
            and receipt.get('kind') in ('construction', 'wall', 'buildings', 'research')
            and isinstance(account, str) and bool(account)
            and marker.get('account') == account
            and marker.get('fingerprint') == fingerprint(receipt)
            and type(marker.get('home_verified_at')) in (int, float)
            and marker['home_verified_at'] > 0)


def paused_result(config):
    return {'status':'deferred', 'retry_at':time.time()+3600,
            'message':'Builder upgrades paused for receipt review; other safe work can continue'}
