"""Resource farming is justified by a verified affordable-capacity upgrade gap.

A free slot alone is not a reason to attack. Missing observations never mean a
builder/lab is free, and prices above storage capacity need progression instead.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FarmingDemand:
    attack: bool
    reason: str
    resource: str | None = None
    target: int | None = None


def farming_demand(observation, *, buildings=True, research=True, reserved=0, reserves=None):
    reserves = reserves or {}
    builders, lab = observation.get('builders'), observation.get('lab')
    def slot(value, maximum):
        return (isinstance(value,(tuple,list)) and len(value)==2
                and all(type(n) is int for n in value)
                and 0<=value[0]<=value[1]<=maximum and value[1]>0)
    building_free = buildings and slot(builders,3) and builders[0]>reserved
    lab = tuple(lab) if slot(lab,1) else None
    lab_free = research and lab==(1,1)
    if not building_free and not lab_free:
        busy=(not buildings or slot(builders,3) and builders[0]<=reserved) and (not research or lab==(0,1))
        return FarmingDemand(False,'All enabled upgrade slots are busy' if busy else 'Upgrade-slot availability is unverified')
    balances, capacities = observation.get('balances',{}), observation.get('capacities',{})
    if all(type(balances.get(r)) is int and type(capacities.get(r)) is int
           and 0<capacities[r]<=balances[r] for r in ('gold','elixir')):
        return FarmingDemand(False,'Both Builder Base storages are full')
    for candidate in observation.get('targets',[]):
        if candidate.get('kind')=='buildings' and not building_free: continue
        if candidate.get('kind')=='research' and not lab_free: continue
        if candidate.get('kind') not in ('buildings','research') or candidate.get('supported') is not True:continue
        resource,cost=candidate.get('currency'),candidate.get('cost')
        if resource not in ('gold','elixir') or type(cost) is not int or cost<=0:continue
        balance,capacity=balances.get(resource),capacities.get(resource)
        reserve=reserves.get(resource,0)
        if type(balance) is not int or balance<0 or type(capacity) is not int or capacity<=0:continue
        if type(reserve) is not int or reserve<0:continue
        target=cost+reserve
        if balance<target<=capacity:
            return FarmingDemand(True,'Resources needed for '+candidate.get('name','a verified upgrade'),resource,target)
    return FarmingDemand(False,'No verified upgrade needs obtainable resources')
