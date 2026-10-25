"""Experimental semantic attack plans. No ADB calls or legacy-sequence migration.

Points refer to a verified battlefield projection, never screenshot pixels.
This contract does not itself authorize execution.
"""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class ArmyEntry:
    unit_id: str
    kind: str
    quantity: int
    confirmed: bool = False


@dataclass(frozen=True)
class MapPoint:
    x: float
    y: float


@dataclass(frozen=True)
class PlanStep:
    action: str
    unit_id: str = ''
    quantity: int = 0
    points: tuple[MapPoint, ...] = ()
    seconds: float = 0


@dataclass(frozen=True)
class AttackPlan:
    army: tuple[ArmyEntry, ...]
    steps: tuple[PlanStep, ...]
    schema_version: int = 1
    mode: str = 'unranked'
    strategy: str = 'mass_electro_dragons'

    def to_dict(self):
        self.validate()
        value = asdict(self)
        # Keep the wire/disk representation identical to JSON decoding. Tuple
        # containers otherwise make an unchanged saved routine compare unequal.
        value['army'] = list(value['army'])
        value['steps'] = [step | {'points': list(step['points'])} for step in value['steps']]
        return value

    @classmethod
    def from_dict(cls, value):
        try:
            if not isinstance(value, dict) or set(value) - {'army','steps','schema_version','mode','strategy'}:
                raise ValueError('Unknown plan fields')
            army = tuple(ArmyEntry(**entry) for entry in value['army'])
            steps = tuple(PlanStep(**(step | {'points':tuple(MapPoint(**p) for p in step.get('points',[]))}))
                          for step in value['steps'])
            return cls(army,steps,**{k:value[k] for k in ('schema_version','mode','strategy') if k in value}).validate()
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError('Invalid attack plan') from exc

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('Unsupported attack plan version')
        if self.mode != 'unranked' or self.strategy not in ('mass_electro_dragons', 'farming_ground', 'mass_dragons'):
            raise ValueError('Unsupported unranked farming strategy')
        inventory = {}
        for entry in self.army:
            if (not isinstance(entry.unit_id, str) or not entry.unit_id.strip() or
                    entry.unit_id in inventory or entry.kind not in ('troop', 'hero', 'siege', 'spell') or
                    type(entry.quantity) is not int or not 1 <= entry.quantity <= 352 or
                    type(entry.confirmed) is not bool):
                raise ValueError('Invalid or duplicate army entry')
            if entry.kind in ('hero', 'siege') and entry.quantity != 1:
                raise ValueError('Heroes and siege entries must have quantity one')
            inventory[entry.unit_id] = entry
        used, activated = {}, set()
        if not self.steps or len(self.steps) > 300:
            raise ValueError('A plan needs between one and 300 steps')
        for step in self.steps:
            if type(step.seconds) not in (int, float) or not math.isfinite(step.seconds) or not 0 <= step.seconds <= 210:
                raise ValueError('Invalid step delay')
            if type(step.quantity) is not int:
                raise ValueError('Step quantity must be an integer')
            for point in step.points:
                if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
                       for v in (point.x, point.y)):
                    raise ValueError('Point outside the normalized battlefield')
            if step.action == 'wait':
                if step.unit_id or step.quantity or step.points or not step.seconds:
                    raise ValueError('Wait steps only contain a positive delay')
                continue
            if step.seconds:
                raise ValueError('Use a separate wait step for delays')
            entry = inventory.get(step.unit_id)
            if entry is None or not entry.confirmed:
                raise ValueError('Every used unit must be identified and confirmed')
            if step.action == 'ability':
                if (entry.kind != 'hero' or used.get(entry.unit_id, 0) != 1 or
                        entry.unit_id in activated or step.points or step.quantity != 1):
                    raise ValueError('A hero ability requires a previously deployed hero and can only run once')
                activated.add(entry.unit_id)
                continue
            if step.action not in ('deploy_point', 'deploy_line', 'cast_points') or step.quantity < 1:
                raise ValueError('Unsupported deployment step')
            if (entry.kind == 'spell') != (step.action == 'cast_points'):
                raise ValueError('Spell placement and troop deployment are different actions')
            expected = 2 if step.action == 'deploy_line' else step.quantity if step.action == 'cast_points' else 1
            if len(step.points) != expected:
                raise ValueError('Deployment geometry does not match the action')
            if step.action == 'deploy_line' and step.points[0] == step.points[1]:
                raise ValueError('Deployment line needs two different endpoints')
            used[entry.unit_id] = used.get(entry.unit_id, 0) + step.quantity
            if used[entry.unit_id] > entry.quantity:
                raise ValueError('Plan deploys more units than the confirmed army contains')
        if sum(step.seconds for step in self.steps) > 210:
            raise ValueError('Combined step delays exceed the battle duration')
        return self


def mass_edrag_plan(army: tuple[ArmyEntry, ...], line: tuple[MapPoint, MapPoint],
                    *, spell_targets: dict[str, tuple[MapPoint, ...]] | None = None,
                    ability_delay: float = 1.0) -> AttackPlan:
    """Build one predictable routine from a corrected army and explicit geometry.

    Spells need explicit per-unit targets: a Recall spell is never treated as Rage.
    Additional troop types require an explicit plan rather than guessed behavior.
    """
    dragons = [entry for entry in army if entry.unit_id == 'electro_dragon' and entry.kind == 'troop']
    if len(dragons) != 1 or any(entry.kind == 'troop' and entry.unit_id != 'electro_dragon' for entry in army):
        raise ValueError('This routine needs a confirmed mass Electro Dragon army')
    if len(line) != 2:
        raise ValueError('Choose two deployment-line endpoints')
    center = MapPoint((line[0].x + line[1].x)/2, (line[0].y + line[1].y)/2)
    steps = [PlanStep('deploy_line', dragons[0].unit_id, dragons[0].quantity, line)]
    for unit_id, targets in (spell_targets or {}).items():
        steps.append(PlanStep('cast_points', unit_id, len(targets), targets))
    for entry in army:
        if entry.kind in ('siege', 'hero'):
            steps.append(PlanStep('deploy_point', entry.unit_id, 1, (center,)))
    heroes = [entry for entry in army if entry.kind == 'hero']
    if heroes:
        if ability_delay:
            steps.append(PlanStep('wait', seconds=ability_delay))
        steps.extend(PlanStep('ability', entry.unit_id, 1) for entry in heroes)
    return AttackPlan(army, tuple(steps)).validate()


def execution_blockers(plan: AttackPlan, *, battle_confirmed: bool,
                       camera_mapped: bool, army_fresh: bool) -> list[str]:
    """Execution needs all three from fresh, independent observations.

    compare_camera()['verified'] alone is NOT camera_mapped. Neither this helper
    nor a valid plan proves that points are legal deployment positions.
    """
    plan.validate()
    return [message for ready, message in (
        (battle_confirmed is True, 'Battlefield not confirmed'),
        (camera_mapped is True, 'Battlefield coordinates not verified'),
        (army_fresh is True, 'Army observation is stale'),
    ) if not ready]
