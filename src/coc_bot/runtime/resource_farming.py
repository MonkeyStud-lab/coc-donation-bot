"""Persistent refill demand. Unknown observations never authorize an attack."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RefillDecision:
    attack: bool
    status: str
    message: str
    resources: tuple = ()


def thresholds(start, stop):
    if type(start) is not int or type(stop) is not int or not 1 <= start < stop <= 100:
        raise ValueError('Resource targets must satisfy 1 ≤ start below < refill to ≤ 100')
    return start, stop


def decide(observation, state, *, start=75, stop=95):
    """Hysteresis over explicitly unlocked resources, using fresh capacities.

    State belongs to one account and village. Never infer locked dark elixir
    from a missing OCR result, nor infer capacities from Town Hall level.
    """
    thresholds(start, stop)
    resources = observation.get('resources')
    balances, capacities = observation.get('balances', {}), observation.get('capacities', {})
    if not resources or any(r not in ('gold', 'elixir', 'dark_elixir') for r in resources):
        return RefillDecision(False, 'unverified', 'Unlocked resources could not be verified')
    for resource in resources:
        balance, capacity = balances.get(resource), capacities.get(resource)
        if (type(balance) is not int or balance < 0 or type(capacity) is not int
                or not 0 < capacity <= 100_000_000):
            return RefillDecision(False, 'unverified', resource+' balance or capacity is unreadable')
    low = tuple(r for r in resources if balances[r]*100 < capacities[r]*start)
    if not state.get('refilling') and not low:
        return RefillDecision(False, 'satisfied', 'Resources are above the refill threshold')
    needed = tuple(r for r in resources if balances[r]*100 < capacities[r]*stop)
    if not needed:
        state['refilling'] = False
        return RefillDecision(False, 'satisfied', 'Resource targets reached')
    state['refilling'] = True
    return RefillDecision(True, 'refilling', 'Refilling '+', '.join(needed), needed)


def record_outcome(state, before, after, resources):
    """Only meaningful loot in a deficient resource resets the failure streak."""
    if not resources or any(type(after.get(r)) is not int or type(before.get(r)) is not int for r in resources):
        return False
    improved = any(after[r] > before[r] for r in resources)
    state['no_progress'] = 0 if improved else state.get('no_progress', 0)+1
    return improved
