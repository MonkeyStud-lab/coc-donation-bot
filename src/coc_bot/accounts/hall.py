"""Persist native current-level observations, never an upgrade-start receipt."""
from pathlib import Path
from loguru import logger
from coc_bot.accounts.store import AccountStore, write


def observe_hall(config, hall):
    """Caller supplies two matching current-Hall observations on this account.

    Updating the shared runtime config also invalidates the layout scheduler's
    old-Hall cooldown. Each profile's layout journal remains separate.
    """
    if type(hall) is not int or not 2 <= hall <= 18:
        return False
    expected = getattr(config,'account_tag',None)
    if not isinstance(expected,str) or not expected:
        return False  # Standalone army readers have no account metadata to refresh.
    known = getattr(config,'account_town_hall',None)
    if type(known) is int and hall < known:
        raise ValueError('Observed Town Hall is below this verified account; no layout change')
    root = Path(config.data_dir).resolve().parent
    if root.parent.name == 'profiles' and root.parent.parent.name == 'accounts' and root.parent.parent.parent.name == 'data':
        root = root.parents[3]
    store = AccountStore(root)
    if not store.path.is_file():
        return False
    with store.lock:
        state = store.load()
        account = next((a for a in state['accounts'] if a['id'] == state['active']), None)
        if (state.get('pending') or account is None or account['tag'] != config.account_tag
            or store.profile(account).resolve() != Path(config.data_dir).resolve().parent):
            raise ValueError('Town Hall observation does not belong to the active account profile')
        old = account.get('town_hall')
        if type(old) is int and hall < old:
            raise ValueError('Town Hall observation conflicts with the saved account')
        if hall != old:
            account['town_hall'] = hall
            write(store.path, state)
        config.account_town_hall = hall
    if known != hall:
        logger.info('Verified Town Hall changed: {} → {} — selecting its defensive layout', known, hall)
    return known != hall
