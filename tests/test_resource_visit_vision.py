"""Current-UI native fixtures from the supervised resource/wall pilot."""
import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock
import cv2
from coc_bot.progression.resources import HomeResources
from coc_bot.progression.bulk_walls import selection,confirmation,control
from coc_bot.accounts.clan import native_clan_tag,clan_tab

ROOT=Path(__file__).parent/'fixtures/resource_visits'


class ResourceNativeTests(unittest.TestCase):
    def test_main_army_housing_retains_three_digits_and_excludes_red_alert(self):
        from coc_bot.progression.preparation import capacity
        self.assertEqual(capacity(cv2.imread(str(ROOT/'main-army-330-340.png'))),(330,340))
    def test_resource_buttons_are_found_after_horizontal_reflow(self):
        import numpy as np
        from coc_bot.progression.bulk_walls import payments
        original=cv2.imread(str(ROOT/'wall-bulk-one.png'))
        frame=np.zeros_like(original)
        frame[748:914,894:1061]=original[748:914,894:1061]
        frame[748:914,694:861]=original[748:914,894:1061]
        result=payments(frame)
        self.assertEqual(sorted(v['pay'][0] for v in result),[776,976])
        self.assertTrue(all(v['currency']=='gold' and v['price']==1000 for v in result))
    def test_both_short_and_long_gold_capacities_are_exact(self):
        nav=Mock();nav._stopping=lambda:False
        reader=HomeResources(nav);reader.home=lambda _:True
        for name,expected in (('starter-gold-capacity.png',8500),('home-gold-capacity.png',30500000)):
            frame=cv2.imread(str(ROOT/name))
            self.assertEqual(reader.storage_capacity(frame,'gold'),expected)
            self.assertIsNone(reader.storage_capacity(frame,'elixir'))
        elixir=cv2.imread(str(ROOT/'starter-elixir-capacity.png'))
        self.assertEqual(reader.storage_capacity(elixir,'elixir'),8500)
        self.assertIsNone(reader.storage_capacity(elixir,'gold'))

    @unittest.skipUnless(shutil.which('tesseract'),'Tesseract is required')
    def test_native_bulk_counts_and_white_red_prices(self):
        for name,count,price,red in (('wall-bulk-one.png',1,1000,False),
                                     ('wall-bulk-two.png',2,2000,False),('wall-bulk-red.png',3,3000,True)):
            observed=selection(cv2.imread(str(ROOT/name)),'gold')
            self.assertIsNotNone(observed,name)
            self.assertEqual((observed['count'],observed['price'],observed['red']),(count,price,red))
            self.assertIsNone(selection(cv2.imread(str(ROOT/name)),'elixir'))

    @unittest.skipUnless(shutil.which('tesseract'),'Tesseract is required')
    def test_bulk_confirmation_never_accepts_wrong_price_or_resource(self):
        frame=cv2.imread(str(ROOT/'wall-confirm.png'))
        self.assertIsNotNone(confirmation(frame,2000,'gold'))
        for price,resource in ((1000,'gold'),(3000,'gold'),(2000,'elixir'),(2000,'gems')):
            self.assertIsNone(confirmation(frame,price,resource))
        self.assertIsNone(confirmation(cv2.imread(str(ROOT/'wall-bulk-red.png')),2000,'gold'))

    @unittest.skipUnless(shutil.which('tesseract'),'Tesseract is required')
    def test_clan_tag_requires_membership_context_not_player_settings(self):
        own=cv2.imread(str(ROOT/'own-clan.png'));settings=cv2.imread(str(ROOT/'settings.png'))
        self.assertEqual(native_clan_tag(own,lambda:False),'#8Y298U8')
        self.assertIsNone(native_clan_tag(settings,lambda:False))
        self.assertIsNotNone(clan_tab(own,lambda:False));self.assertIsNotNone(clan_tab(settings,lambda:False))
