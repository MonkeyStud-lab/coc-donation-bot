"""Upgrade eligibility is independent of navigation and never uses color alone."""
from coc_bot.upgrades.vision import compact, pet_name

PROTECTED = {
    'townhall','wall','walls','laboratory','barracks','darkbarracks','spellfactory',
    'darkspellfactory','workshop','herohall','pethouse','barbarianking','archerqueen',
    'grandwarden','royalchampion','minionprince','dragonduke','battlemachine','battlecopter',
}
BUILDINGS = {compact(name) for name in (
    "Blacksmith", "Builder's Hut", "Army Camp", "Gold Mine", "Elixir Collector",
    "Dark Elixir Drill", "Gold Storage", "Elixir Storage", "Dark Elixir Storage",
    "Cannon", "Archer Tower", "Mortar", "Air Defense", "Wizard Tower", "Air Sweeper",
    "Hidden Tesla", "Bomb Tower", "X-Bow", "Inferno Tower", "Eagle Artillery",
    "Scattershot", "Monolith", "Spell Tower", "Ricochet Cannon", "Multi-Archer Tower",
    "Multi-Gear Tower", "Firespitter", "Bomb", "Giant Bomb", "Air Bomb", "Seeking Air Mine",
    "Spring Trap", "Skeleton Trap", "Tornado Trap",
)}


def reason(config, kind, candidate, balances, availability):
    if kind not in ('buildings','research','pets'):
        return 'Unsupported upgrade category'
    if availability is None:
        return 'Upgrade-slot availability could not be verified'
    free,total=availability
    if kind=='pets' and (total!=1 or type(free) is not int or free not in (0,1)):
        return 'Pet-upgrade slot could not be verified'
    if free <= (config.upgrade_builders_reserved if kind=='buildings' else 0):
        return {'buildings':'No spare builders','research':'Research is already busy',
                'pets':'Pet upgrade is already busy or unavailable'}[kind]
    if compact(candidate.name) in PROTECTED:
        return 'Excluded from automatic upgrades'
    if kind=='buildings' and compact(candidate.name) not in BUILDINGS:
        return 'Unrecognized building or excluded hero; no upgrade allowed'
    if kind=='pets':
        if pet_name(candidate.name) is None or candidate.currency!='dark_elixir':
            return 'Unrecognized pet or dark-elixir price; no upgrade allowed'
        if type(candidate.assigned) is not bool:
            return 'Pet assignment could not be verified'
        if candidate.assigned and not getattr(config,'upgrade_pets_include_assigned',False):
            return 'Equipped pets are excluded in upgrade settings'
    exclusions={compact(name) for name in config.upgrade_excluded_names.split(',') if name.strip()}
    if compact(candidate.name) in exclusions:
        return 'Excluded in upgrade settings'
    floors={'gold':config.upgrade_gold_reserve,'elixir':config.upgrade_elixir_reserve,
            'dark_elixir':config.upgrade_dark_elixir_reserve}
    if candidate.currency not in floors or candidate.cost<=0:
        return 'Unverified resource price; gems and items are never used'
    balance=balances.get(candidate.currency)
    maximum=2_000_000 if candidate.currency=='dark_elixir' else 100_000_000
    if type(balance) is not int or not 0<=balance<=maximum:
        return 'Resource balance could not be verified'
    if balance-candidate.cost < floors[candidate.currency]:
        return 'Would fall below the resource reserve'
    return None
