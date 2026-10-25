from dataclasses import replace
import unittest

from coc_bot.progression.profiles import (PROFILES,HOME_PROFILES,BUILDER_PROFILES,
    Capabilities,blockers,recommend)


class ProfileTests(unittest.TestCase):
    def capabilities(self,p):
        return Capabilities(p.village,p.hall,p.capacity,p.spell_capacity,
            sum(n for _,n in p.reinforcements),
            {u:1 for u,n in p.troops+p.spells+p.reinforcements},100,True)

    def test_all_halls_and_capacity_arithmetic(self):
        self.assertEqual([p.hall for p in HOME_PROFILES],list(range(1,19)))
        self.assertEqual([p.hall for p in BUILDER_PROFILES],list(range(1,11)))
        self.assertEqual(len({p.id for p in PROFILES}),28)
        for p in PROFILES:
            with self.subTest(p=p.id):
                p.validate()
                if p.hall>1:
                    self.assertEqual(blockers(p,self.capabilities(p),now=101,automatic=False),[])

    def test_live_release_gate_does_not_confuse_capacity_tests_with_real_validation(self):
        for p in PROFILES:
            self.assertIsNone(recommend(self.capabilities(p),now=101))
        self.assertIn('Tutorial requires manual play',blockers(HOME_PROFILES[0],self.capabilities(HOME_PROFILES[0]),now=101,automatic=False))

    def test_rushed_hall_falls_back_to_an_intact_smaller_composition(self):
        p=HOME_PROFILES[6];caps=replace(self.capabilities(p),hall=10)
        self.assertEqual(recommend(caps,now=101,automatic=False).id,'home-th7')
        # Capacity alone never unlocks Freeze or Poison.
        caps=replace(caps,capacity=240,spell_capacity=11)
        self.assertEqual(recommend(caps,now=101,automatic=False).id,'home-th7')

    def test_stale_conflicting_or_incomplete_capabilities_block_selection(self):
        p=HOME_PROFILES[10];caps=self.capabilities(p)
        for changed in (replace(caps,verified=False),replace(caps,observed_at=500),
                        replace(caps,observed_at=float('nan')),replace(caps,observed_at=-500),
                        replace(caps,hall=999),replace(caps,hall=True),replace(caps,unit_levels={}),
                        replace(caps,capacity=0),replace(caps,spell_capacity=0)):
            self.assertIsNone(recommend(changed,now=101,automatic=False))

    def test_builder_capacity_means_camps_and_reinforcements_are_separate(self):
        p=BUILDER_PROFILES[8];caps=self.capabilities(p)
        self.assertEqual(p.capacity,6)
        self.assertTrue(blockers(p,replace(caps,reinforcement_camps=1),now=101,automatic=False))
        self.assertTrue(blockers(p,replace(caps,capacity=5),now=101,automatic=False))

    def test_invalid_profiles_are_rejected(self):
        p=HOME_PROFILES[6]
        for changed in (replace(p,troops=(('dragon',True),)),replace(p,troops=(('dragon',11),)),
                        replace(p,spells=(('rage',4),)),replace(p,spells=(('gems',1),)),
                        replace(p,troops=(('dragon',5),('dragon',5))),
                        replace(p,reinforcements=(('night_witch',1),))):
            with self.assertRaises(ValueError):changed.validate()


if __name__=='__main__':unittest.main()
