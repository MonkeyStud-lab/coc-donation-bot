"""Built-in Electro Dragon farming, with no saved plan or manual map review."""
from dataclasses import replace
from loguru import logger

from coc_bot.attack.army import agree_cards, check_stop, read_army
from coc_bot.attack.battle_gate import BattleFrameGate
from coc_bot.attack.plans import ArmyEntry, MapPoint, PlanStep, mass_edrag_plan


SIEGE_UNITS = {'wall_wrecker', 'battle_blimp', 'stone_slammer', 'siege_barracks',
               'log_launcher', 'flame_flinger', 'battle_drill'}
RAGE_UNITS = {'rage', 'rage_spell'}


def supported_identity(card, *, progression=False):
    from coc_bot.progression.army import TROOPS
    return (card.kind == 'troop' and (card.unit_id == 'electro_dragon' or progression and card.unit_id in TROOPS)
            or card.kind == 'spell' and card.unit_id in RAGE_UNITS
            or card.kind == 'siege' and card.unit_id in SIEGE_UNITS
            or card.kind == 'hero' and bool(card.unit_id))


def automatic_plan(cards, *, progression=False, deploy_line=None):
    """Only stable identities/counts authorize this fixed, supported strategy.

    Known hero artwork may use a user-supplied name. Hero slot order never
    establishes identity. Extra/unknown cards are left unused; they cannot
    veto a positively identified Electro Dragon army or authorize any tap.
    """
    if progression:
        from coc_bot.progression.army import farming_plan
        return farming_plan(cards,deploy_line=deploy_line)
    if not cards:
        raise ValueError('Automatic attack skipped: no readable army cards')
    army = []
    seen = set()
    for card in cards:
        if not supported_identity(card):
            logger.info('Automatic attack: leaving extra card unused ({})', card.unit_id or card.slot)
            continue
        if (not card.stable or not card.unit_id or type(card.quantity) is not int
                or card.quantity < 1):
            raise ValueError('Automatic attack skipped: an army card or its quantity is uncertain')
        if card.unit_id in seen:
            raise ValueError('Automatic attack skipped: duplicate army identity')
        seen.add(card.unit_id)
        supported = (
            card.kind == 'troop' and card.unit_id == 'electro_dragon' and card.quantity <= 20
            or card.kind == 'spell' and card.unit_id in RAGE_UNITS and card.quantity <= 11
            or card.kind == 'siege' and card.unit_id in SIEGE_UNITS and card.quantity == 1
            or card.kind == 'hero' and card.quantity == 1
        )
        if not supported:
            raise ValueError('Automatic attack skipped: invalid supported unit quantity: '+card.unit_id)
        army.append(ArmyEntry(card.unit_id, card.kind, card.quantity, True))
    if not any(e.unit_id == 'electro_dragon' and e.kind == 'troop' for e in army):
        raise ValueError('Automatic attack skipped: no verified Electro Dragons')
    if sum(e.kind == 'hero' for e in army) > 4 or sum(e.kind == 'siege' for e in army) > 1:
        raise ValueError('Automatic attack skipped: ambiguous hero or siege inventory')
    if sum(e.kind == 'spell' for e in army) > 1:
        raise ValueError('Automatic attack skipped: ambiguous Rage inventory')
    spells = {entry.unit_id: tuple(MapPoint(.27, .5 if entry.quantity == 1 else
                        .22+i*.56/(entry.quantity-1)) for i in range(entry.quantity))
              for entry in army if entry.kind == 'spell'}
    plan = mass_edrag_plan(tuple(army), (MapPoint(.055, .22), MapPoint(.055, .78)),
                          spell_targets=spells)
    heroes = {entry.unit_id for entry in army if entry.kind == 'hero'}
    steps = []
    for step in plan.steps:
        if step.action in ('wait', 'ability'):
            continue
        steps.append(step)
        if step.unit_id in heroes:
            steps.append(PlanStep('ability', step.unit_id, 1))
    return replace(plan, steps=tuple(steps)).validate()


def same_page(before, after):
    """An unchanged card row after a swipe proves a bounded scroll endpoint."""
    return bool(before) and len(before) == len(after) and all(
        (a.unit_id, a.kind, a.quantity) == (b.unit_id, b.kind, b.quantity)
        and max(abs(x-y) for x,y in zip(a.box,b.box)) <= 6
        for a,b in zip(before,after))


def scan_army(session, catalog):
    """Inspect both ends of the army bar, never selecting a unit or map point.

    Every page uses two fresh battle frames. Duplicate units across overlapping
    pages are merged, never added; mismatching counts of used units abort.
    Unrecognized/extra cards are never selected or used as scroll anchors.
    The returned reference artwork is transient and cannot overwrite calibration.
    """
    stop = session.client.stop_check
    progression = getattr(session.config, 'progression_enabled', False)
    gate = BattleFrameGate(session.attack_nav.battlefield_ready)
    last_shape = None
    row = []

    def page():
        nonlocal last_shape, row
        check_stop(stop)
        first = session.capture.screenshot()
        if not gate.accept(first):
            raise ValueError('Automatic attack skipped: battle controls changed while reading army')
        session._sleep(.2)
        check_stop(stop)
        second = session.capture.screenshot()
        if first.shape != second.shape or not gate.accept(second):
            raise ValueError('Automatic attack skipped: battle changed while reading army')
        if last_shape is not None and last_shape != second.shape:
            raise ValueError('Automatic attack skipped: display size changed')
        last_shape = second.shape
        before = read_army(first, 'battle', catalog, stop_check=stop)
        observed = agree_cards(before, read_army(second, 'battle', catalog, stop_check=stop))
        after = []
        for card in observed:
            if not supported_identity(card, progression=progression):
                logger.debug('Automatic army: ignoring unused card {} ({})',card.slot,card.unit_id or 'unrecognized')
                continue
            if not card.stable:
                raise ValueError('Automatic attack skipped: unreadable or changing army card: '+card.unit_id)
            after.append(card)
        if not after:
            raise ValueError('Automatic attack skipped: unreadable supported army cards')
        if len({c.unit_id for c in after}) != len(after):
            raise ValueError('Automatic attack skipped: duplicate card identity on one page')
        catalog.add_references(second, after)
        row = after
        return after

    def swipe(direction):
        check_stop(stop)
        fresh = session.capture.screenshot()
        if fresh.shape != last_shape or not gate.accept(fresh):
            raise ValueError('Automatic attack skipped: battle changed before army scroll')
        h,w = last_shape[:2]
        # Start on an observed card. Empty space beyond a short army row belongs
        # to the battlefield and could pan the village instead of the army bar.
        x,y,cw,ch = (row[0] if direction == 'beginning' else row[-1]).box
        start = x+cw//2
        end = min(round(w*.92),start+round(w*.40)) if direction == 'beginning' else max(round(w*.08),start-round(w*.40))
        cy = min(round(h*.97),y+round(ch*.65))
        session.input.swipe(start, cy, end, cy, 350)
        session._sleep(.3)
        return page()

    logger.info('Automatic attack: reading army bar')
    cards = page()
    for _ in range(4):
        previous = cards
        cards = swipe('beginning')
        if same_page(previous, cards):
            break
    else:
        raise ValueError('Automatic attack skipped: could not find the start of the army bar')

    inventory = {}
    for index in range(7):
        for card in cards:
            old = inventory.get(card.unit_id)
            if old and (old.kind, old.quantity) != (card.kind, card.quantity):
                raise ValueError('Automatic attack skipped: army changed between pages')
            inventory[card.unit_id] = card
        if index == 6:
            break
        previous = cards
        cards = swipe('end')
        if same_page(previous, cards):
            return list(inventory.values())
    raise ValueError('Automatic attack skipped: could not confirm the end of the army bar')
