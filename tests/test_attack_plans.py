from dataclasses import replace
from unittest import TestCase

from coc_bot.attack.plans import ArmyEntry, MapPoint, PlanStep, AttackPlan, mass_edrag_plan, execution_blockers


class AttackPlanTests(TestCase):
    def setUp(self):
        self.army = (ArmyEntry('electro_dragon', 'troop', 11, True),
                     ArmyEntry('king', 'hero', 1, True), ArmyEntry('siege', 'siege', 1, True),
                     ArmyEntry('rage', 'spell', 5, True), ArmyEntry('recall', 'spell', 1, True))
        self.line = (MapPoint(.1, .2), MapPoint(.1, .8))

    def test_routine_uses_army_quantities_and_explicit_spell_identity(self):
        targets = tuple(MapPoint(.4, .2+i*.1) for i in range(5))
        plan = mass_edrag_plan(self.army, self.line, spell_targets={'rage':targets})
        self.assertEqual(plan.steps[0].quantity, 11)
        self.assertEqual([s.action for s in plan.steps],
                         ['deploy_line', 'cast_points', 'deploy_point', 'deploy_point', 'wait', 'ability'])
        self.assertEqual(plan.steps[1].unit_id, 'rage')
        self.assertFalse(any(s.unit_id == 'recall' for s in plan.steps))
        self.assertEqual(plan.to_dict()['schema_version'], 1)

    def test_uncertain_army_unsupported_troops_and_overdraw_are_rejected(self):
        for army, targets in [(tuple(replace(e, confirmed=False) for e in self.army), None),
                              (self.army+(ArmyEntry('barbarian', 'troop', 2, True),), None),
                              (self.army, {'rage':tuple(MapPoint(.5,.5) for _ in range(6))})]:
            with self.assertRaises(ValueError):
                mass_edrag_plan(army, self.line, spell_targets=targets)

    def test_invalid_coordinates_versions_and_ability_order_cannot_execute(self):
        plan = mass_edrag_plan(self.army, self.line)
        for changed in [replace(plan, schema_version=True), replace(plan, mode='ranked'),
                        replace(plan, steps=(PlanStep('ability','king',1),)),
                        replace(plan, steps=(PlanStep('wait',seconds=200), PlanStep('wait',seconds=20))),
                        replace(plan, steps=(PlanStep('deploy_point','electro_dragon',1,(MapPoint(float('nan'),0),)),)),
                        replace(plan, steps=(PlanStep('deploy_point','electro_dragon',True,(MapPoint(.5,.5),)),))]:
            with self.assertRaises(ValueError):
                changed.validate()

    def test_duplicate_abilities_and_spell_as_troop_are_rejected(self):
        for steps in [(PlanStep('deploy_point','king',1,(self.line[0],)),
                       PlanStep('ability','king',1), PlanStep('ability','king',1)),
                      (PlanStep('deploy_point','rage',1,(self.line[0],)),)]:
            with self.assertRaises(ValueError):
                AttackPlan(self.army, steps).validate()

    def test_camera_gesture_alone_does_not_pass_preflight(self):
        plan = mass_edrag_plan(self.army, self.line)
        self.assertEqual(len(execution_blockers(plan,battle_confirmed=False,camera_mapped=False,army_fresh=False)),3)
        self.assertEqual(execution_blockers(plan,battle_confirmed=True,camera_mapped=False,army_fresh=True),
                         ['Battlefield coordinates not verified'])
        self.assertFalse(execution_blockers(plan,battle_confirmed=True,camera_mapped=True,army_fresh=True))
