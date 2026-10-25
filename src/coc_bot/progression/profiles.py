"""Versioned candidate armies, independent of UI positions and spending.

These are research compositions, not a claim of live support at every hall.
The certified profile selector requires an explicit release. The opt-in Home
Village pilot uses reference ratios through progression.army with separate live
unlock/capacity checks; this is not certification of every reference preset.
Observed unlocks and capacities override the reference hall table.
"""
from dataclasses import dataclass
import math


VERSION='2026-10-24.1'
HOUSING={'barbarian':1,'archer':1,'giant':5,'wall_breaker':2,'wizard':4,
         'dragon':20,'electro_dragon':30,'balloon':5}
SPELL_SPACE={'lightning':1,'healing':2,'rage':2,'poison':1,'freeze':1}
BUILDER_UNITS={'raged_barbarian','boxer_giant','baby_dragon','night_witch','power_pekka','bomber'}


@dataclass(frozen=True)
class ArmyProfile:
    id: str
    village: str
    hall: int
    family: str
    troops: tuple[tuple[str,int],...]
    spells: tuple[tuple[str,int],...]=()
    reinforcements: tuple[tuple[str,int],...]=()
    reference_capacity: int=0
    reference_spell_capacity: int=0
    automatic_released: bool=False
    version: str=VERSION

    def validate(self):
        if self.village not in ('home','builder') or type(self.hall) is not int or not 1<=self.hall<=(18 if self.village=='home' else 10):
            raise ValueError('Invalid village/hall')
        for entries,registry in ((self.troops,HOUSING if self.village=='home' else BUILDER_UNITS),
                                 (self.spells,SPELL_SPACE),(self.reinforcements,BUILDER_UNITS)):
            if len({name for name,_ in entries})!=len(entries):
                raise ValueError('Duplicate unit')
            if any(name not in registry or type(count) is not int or count<1 for name,count in entries):
                raise ValueError('Invalid unit/count')
        if not self.troops or self.capacity != self.reference_capacity:
            raise ValueError('Composition does not fill its declared reference capacity')
        if self.spell_capacity > self.reference_spell_capacity:
            raise ValueError('Spell capacity exceeded')
        if self.village=='home' and self.reinforcements or self.village=='builder' and self.spells:
            raise ValueError('Resources cannot cross village types')
        if self.hall==1 and self.automatic_released:
            raise ValueError('Tutorial profiles cannot be released for automatic play')
        maximum=0 if self.village=='home' or self.hall<6 else 1 if self.hall<9 else 2
        if sum(n for _,n in self.reinforcements)>maximum:
            raise ValueError('Too many reference reinforcement camps')
        return self

    @property
    def capacity(self):
        return sum(count*(HOUSING[name] if self.village=='home' else 1) for name,count in self.troops)

    @property
    def spell_capacity(self):
        return sum(SPELL_SPACE[name]*count for name,count in self.spells)


def _home(hall, capacity, troops, spells=(), spell_capacity=0):
    family='electro_dragons' if hall>=11 else 'dragons' if hall>=7 else 'ground'
    return ArmyProfile(f'home-th{hall}','home',hall,family,tuple(troops),tuple(spells),
                       reference_capacity=capacity,reference_spell_capacity=spell_capacity).validate()


HOME_PROFILES=(
    _home(1,20,(('barbarian',20),)),
    _home(2,30,(('giant',2),('barbarian',10),('archer',10))),
    _home(3,70,(('giant',8),('wall_breaker',2),('archer',20),('barbarian',6))),
    _home(4,80,(('giant',8),('wall_breaker',5),('archer',30))),
    _home(5,135,(('giant',12),('wizard',12),('wall_breaker',4),('archer',19)),(('lightning',2),),2),
    _home(6,150,(('giant',14),('wizard',16),('wall_breaker',4),('archer',8)),(('healing',2),),4),
    _home(7,200,(('dragon',10),),(('rage',3),),6),
    _home(8,200,(('dragon',10),),(('rage',3),('poison',1)),7),
    _home(9,220,(('dragon',11),),(('rage',4),('freeze',1)),9),
    _home(10,240,(('dragon',12),),(('rage',4),('freeze',3)),11),
    *(_home(hall,cap,tuple(troops),(('rage',5),('freeze',1)),11) for hall,cap,troops in (
        (11,260,[('electro_dragon',8),('balloon',4)]),
        (12,280,[('electro_dragon',9),('balloon',2)]),
        (13,300,[('electro_dragon',9),('balloon',6)]),
        (14,300,[('electro_dragon',9),('balloon',6)]),
        (15,320,[('electro_dragon',10),('balloon',4)]),
        (16,320,[('electro_dragon',10),('balloon',4)]),
        (17,340,[('electro_dragon',11),('balloon',2)]),
        (18,352,[('electro_dragon',11),('balloon',4),('archer',2)]))),
)


BUILDER_PROFILES=tuple(ArmyProfile(f'builder-bh{hall}','builder',hall,family,tuple(troops),
    reinforcements=tuple(reinforcements),reference_capacity=camps).validate()
    for hall,camps,family,troops,reinforcements in (
        (1,1,'ground',[('raged_barbarian',1)],[]),
        (2,2,'ground',[('raged_barbarian',2)],[]),
        (3,3,'ground',[('boxer_giant',1),('raged_barbarian',2)],[]),
        (4,4,'baby_dragons',[('baby_dragon',4)],[]),
        (5,4,'baby_dragons',[('baby_dragon',4)],[]),
        (6,5,'baby_dragons',[('baby_dragon',5)],[('baby_dragon',1)]),
        (7,6,'baby_dragons',[('baby_dragon',6)],[('baby_dragon',1)]),
        (8,6,'pekka_bomber',[('power_pekka',5),('bomber',1)],[('power_pekka',1)]),
        (9,6,'pekka_bomber',[('power_pekka',5),('bomber',1)],[('power_pekka',2)]),
        (10,6,'pekka_bomber',[('power_pekka',5),('bomber',1)],[('power_pekka',2)]),
    ))
PROFILES=HOME_PROFILES+BUILDER_PROFILES


@dataclass(frozen=True)
class Capabilities:
    village: str
    hall: int
    capacity: int
    spell_capacity: int
    reinforcement_camps: int
    unit_levels: dict[str,int]
    observed_at: float
    verified: bool=False


def blockers(profile, caps, *, now, automatic=True):
    """No hall inference, rounding of counts, or silent use of stale snapshots."""
    profile.validate()
    reasons=[]
    if (type(caps.hall) is not int or not 1<=caps.hall<=(18 if caps.village=='home' else 10)
            or caps.village not in ('home','builder') or not isinstance(caps.unit_levels,dict)):
        return ['Invalid account capabilities']
    if (caps.verified is not True or type(caps.observed_at) not in (float,int)
            or not math.isfinite(caps.observed_at) or not 0<=now-caps.observed_at<=300):
        reasons.append('Account capabilities need two fresh agreeing observations')
    if (caps.village != profile.village or type(caps.hall) is not int
            or caps.hall<profile.hall):
        reasons.append('Village/hall mismatch')
    if type(caps.capacity) is not int or caps.capacity<profile.capacity:
        reasons.append('Insufficient observed troop/camp capacity')
    if type(caps.spell_capacity) is not int or caps.spell_capacity<profile.spell_capacity:
        reasons.append('Insufficient observed spell capacity')
    if (type(caps.reinforcement_camps) is not int or
            caps.reinforcement_camps<sum(n for _,n in profile.reinforcements)):
        reasons.append('Insufficient observed reinforcement camps')
    for unit,_ in profile.troops+profile.spells+profile.reinforcements:
        level=caps.unit_levels.get(unit)
        if type(level) is not int or level<1:
            reasons.append(f'Unit not verified unlocked: {unit}')
    if profile.hall==1:
        reasons.append('Tutorial requires manual play')
    if automatic and not profile.automatic_released:
        reasons.append('This profile has not passed live release tests')
    return reasons


def recommend(caps, *, now, automatic=True):
    eligible=[p for p in PROFILES if not blockers(p,caps,now=now,automatic=automatic)]
    return max(eligible,key=lambda p:(p.hall,p.capacity)) if eligible else None
