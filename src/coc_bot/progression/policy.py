"""Progression ordering never mistakes affordability or a partial list for maxing."""
from coc_bot.upgrades.vision import compact

ARMY_BUILDINGS = ('armycamp', 'barracks', 'laboratory', 'spellfactory', 'darkspellfactory',
                  'darkbarracks', 'clancastle', 'goldstorage', 'elixirstorage')
EXTRA_BUILDINGS = {'laboratory', 'barracks', 'darkbarracks', 'spellfactory',
                   'darkspellfactory', 'workshop', 'herohall', 'pethouse', 'clancastle', 'wall'}
HEROES = {'barbarianking', 'archerqueen', 'grandwarden', 'royalchampion', 'minionprince', 'dragonduke'}


def deferred_starter_castle(row, inventory):
    """Explicit TH2-only rebuild exception; affordability never maxes other rows."""
    balance=inventory.get('balances',{}).get('elixir')
    return (inventory.get('hall')==2 and inventory.get('hall_verified') is True
            and compact(row.get('name',''))=='clancastle' and row.get('target_level')==1
            and row.get('currency')=='elixir' and row.get('cost')==10_000
            and type(balance) is int and 0<=balance<10_000)


def town_hall_blockers(inventory):
    reasons = []
    if inventory.get('complete') is not True or inventory.get('unfiltered') is not True:
        reasons.append('The complete unfiltered building list has not been verified')
    if inventory.get('unknown'):
        reasons.append('Some building rows could not be read')
    if inventory.get('busy') is not False:
        reasons.append('Existing construction or upgrades must finish first')
    for row in inventory.get('rows', []):
        name = compact(row.get('name', ''))
        if row.get('currency') == 'gems' or name in HEROES:
            continue
        if name == 'townhall' or row.get('state') in ('maxed', 'future_locked') or deferred_starter_castle(row,inventory):
            continue
        reasons.append(('Build ' if row.get('new') else 'Finish upgrading ') + row.get('name', 'unknown building'))
    if not any(compact(r.get('name', '')) == 'townhall' for r in inventory.get('rows', [])):
        reasons.append('A Town Hall upgrade has not been verified')
    return reasons


def priority(row):
    name = compact(row['name'])
    return (0 if row.get('new') else 2 if name == 'townhall' else 1,
            ARMY_BUILDINGS.index(name) if name in ARMY_BUILDINGS else len(ARMY_BUILDINGS)+(name=='wall'),
            row.get('cost') or 0)
