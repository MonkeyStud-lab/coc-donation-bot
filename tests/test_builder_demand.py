import unittest
from coc_bot.builder_base.demand import farming_demand


class DemandTests(unittest.TestCase):
    def observation(self, **values):
        return {'builders':(1,2),'lab':(0,1),'balances':{'gold':1000,'elixir':2000},
                'capacities':{'gold':10000,'elixir':10000},'targets':[
                    {'kind':'buildings','name':'Cannon','currency':'gold','cost':5000,'supported':True}]}|values

    def test_busy_builders_and_lab_never_attack_even_with_empty_storages(self):
        r=farming_demand(self.observation(builders=(0,3)))
        self.assertFalse(r.attack);self.assertIn('busy',r.reason)

    def test_full_or_overflowed_storages_never_attack(self):
        self.assertFalse(farming_demand(self.observation(balances={'gold':10000,'elixir':12000})).attack)

    def test_real_upgrade_shortfall_can_be_farmed(self):
        r=farming_demand(self.observation())
        self.assertTrue(r.attack);self.assertEqual((r.resource,r.target),('gold',5000))

    def test_busy_builders_can_still_fund_free_research(self):
        obs=self.observation(builders=(0,2),lab=[1,1],targets=[
            {'kind':'research','name':'Night Witch','cost':5000,'currency':'elixir','supported':True}])
        self.assertTrue(farming_demand(obs).attack)
        self.assertFalse(farming_demand(obs,research=False).attack)

    def test_unknown_or_impossible_upgrade_does_not_start_attacks(self):
        for values in ({'capacities':{}},{'builders':None}, {'targets':[]},
                       {'targets':[{'kind':'buildings','currency':'gems','cost':5,'supported':True}]},
                       {'targets':[{'kind':'buildings','currency':'gold','cost':11000,'supported':True}]},
                       {'targets':[{'kind':'buildings','currency':'gold','cost':5000,'supported':False}]}):
            with self.subTest(values=values):self.assertFalse(farming_demand(self.observation(**values)).attack)

    def test_reserves_and_reserved_builders_still_apply(self):
        self.assertFalse(farming_demand(self.observation(),reserved=1).attack)
        self.assertFalse(farming_demand(self.observation(),reserves={'gold':10000}).attack)
        self.assertFalse(farming_demand(self.observation(balances={'gold':6000,'elixir':2000})).attack)
