"""Capacity-aware farming compositions and predictable deployment families."""
from coc_bot.progression.profiles import HOME_PROFILES, HOUSING
from coc_bot.attack.plans import ArmyEntry, AttackPlan, PlanStep, MapPoint

GROUND = ('giant', 'wall_breaker', 'barbarian', 'wizard', 'archer')
TROOPS = set(HOUSING)


def composition(hall, capacity, unlocked):
    """Use observed unlocks/capacity, including a Barbarian-only starter army."""
    if type(hall) is not int or not 2 <= hall <= 18 or type(capacity) is not int or not 1 <= capacity <= 352:
        raise ValueError('Verify Town Hall and army capacity first')
    available = {unit for unit, level in unlocked.items() if type(level) is int and level > 0}
    if hall>=11 and 'electro_dragon' in available and capacity>=HOUSING['electro_dragon']:
        # One farming family after its real unlock; do not mix in other troops
        # merely to fill a few spare housing spaces or match an older preset.
        return {'electro_dragon':capacity//HOUSING['electro_dragon']}
    eligible = [p for p in HOME_PROFILES if 2 <= p.hall <= hall and all(u in available for u, _ in p.troops)]
    # A missing filler identity must not reject a verified mass-air army or
    # downgrade it to a starter composition. Spare camp space may remain empty;
    # never invent an unlock merely to fill the last few housing spaces.
    air = next((u for u, minimum in (('electro_dragon',11),('dragon',7))
                if hall >= minimum and u in available), None)
    if air and capacity >= HOUSING[air] and not any(p.troops[0][0] == air for p in eligible):
        counts = {air:capacity//HOUSING[air]}
        remaining = capacity % HOUSING[air]
        for unit in ('archer','barbarian','balloon'):
            if unit in available:
                amount = remaining//HOUSING[unit]
                if amount:counts[unit] = amount
                remaining -= amount*HOUSING[unit]
        return counts
    if not eligible:
        basic = [u for u in ('barbarian', 'archer') if u in available]
        if not basic:
            raise ValueError('No verified supported farming troops are unlocked')
        counts = {u: capacity // len(basic) for u in basic}
        counts[basic[0]] += capacity - sum(counts.values())
        return {u: n for u, n in counts.items() if n}
    profile = max(eligible, key=lambda p: p.hall)
    counts = {u: int(n * min(1, capacity / profile.capacity)) for u, n in profile.troops}
    remaining = capacity - sum(HOUSING[u] * n for u, n in counts.items())
    # Fill with the family's main unit, then small verified units; never invent unlocks.
    for unit in [profile.troops[0][0], 'archer', 'barbarian', 'balloon']:
        if unit in available:
            n = remaining // HOUSING[unit]
            counts[unit] = counts.get(unit, 0) + n
            remaining -= n * HOUSING[unit]
    return {u: n for u, n in counts.items() if n}


def research_priority(unit):
    """An explicit army order, independent of Suggested row position."""
    return ('electro_dragon', 'dragon', 'giant', 'wizard', 'archer', 'barbarian',
            'balloon', 'wall_breaker', 'rage', 'healing', 'lightning', 'freeze', 'poison').index(unit)


def farming_plan(cards, *, deploy_line=None):
    troops = [c for c in cards if c.kind == 'troop']
    if not troops or any(c.unit_id not in TROOPS or not c.stable or type(c.quantity) is not int
                         or not 1 <= c.quantity <= 352 for c in troops):
        raise ValueError('Farming troop identities and quantities must be verified')
    if len({c.unit_id for c in troops}) != len(troops):
        raise ValueError('Duplicate farming troop identity')
    total = sum(HOUSING[c.unit_id] * c.quantity for c in troops)
    if total > 352:
        raise ValueError('Observed army exceeds supported capacity')
    air = any(c.unit_id in ('dragon', 'electro_dragon') for c in troops)
    allowed = {'dragon', 'electro_dragon', 'balloon', 'archer', 'barbarian'} if air else set(GROUND)
    if any(c.unit_id not in allowed for c in troops):
        raise ValueError('Unsupported combination of farming families')
    line = deploy_line or (MapPoint(.055, .27), MapPoint(.055, .73))
    army = tuple(ArmyEntry(c.unit_id, 'troop', c.quantity, True) for c in troops)
    by_id = {e.unit_id: e for e in army}
    order = ('balloon', 'dragon', 'electro_dragon', 'barbarian', 'archer') if air else GROUND
    steps = []
    for unit in order:
        if unit not in by_id:
            continue
        count = by_id[unit].quantity
        steps.append(PlanStep('deploy_line', unit, count, line))
        if unit == 'giant':
            steps.append(PlanStep('wait', seconds=1))
    extra = []
    for card in cards:
        if card.kind not in ('hero','siege','spell') or not card.unit_id:
            continue
        if card.kind == 'spell' and card.unit_id not in ('rage','rage_spell'):
            continue
        if not card.stable or type(card.quantity) is not int or card.quantity<1:
            raise ValueError('Supported farming support card is uncertain')
        if card.kind in ('hero','siege') and card.quantity != 1 or card.kind=='spell' and card.quantity>11:
            raise ValueError('Invalid farming support quantity')
        extra.append(ArmyEntry(card.unit_id,card.kind,card.quantity,True))
    if sum(e.kind=='hero' for e in extra)>4 or sum(e.kind=='siege' for e in extra)>1 or sum(e.kind=='spell' for e in extra)>1:
        raise ValueError('Ambiguous farming support inventory')
    # Inventory order follows army-bar pages; it must not delay Rage until after
    # slow hero selection/verification. Always cast support immediately after troops.
    for entry in sorted(extra,key=lambda e:{'spell':0,'siege':1,'hero':2}[e.kind]):
        if entry.kind=='spell':
            targets=tuple(MapPoint(.27,.5 if entry.quantity==1 else .22+i*.56/(entry.quantity-1)) for i in range(entry.quantity))
            steps.append(PlanStep('cast_points',entry.unit_id,entry.quantity,targets))
        else:
            steps.append(PlanStep('deploy_point',entry.unit_id,1,(MapPoint(.055,.5),)))
            if entry.kind=='hero':steps.append(PlanStep('ability',entry.unit_id,1))
    strategy='mass_electro_dragons' if 'electro_dragon' in by_id else 'mass_dragons' if air else 'farming_ground'
    return AttackPlan(army+tuple(extra), tuple(steps), strategy=strategy).validate()
