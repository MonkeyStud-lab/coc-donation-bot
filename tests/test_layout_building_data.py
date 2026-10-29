"""Synthetic static-data tests; no proprietary game tables or device required."""
from unittest import TestCase
from coc_bot.layouts.building_data import BuildingCatalog

BUILDINGS='''Name,GlobalID,BuildingLevel,Width,Height,VillageType,BuildingClass,Hidden
String,int,int,int,int,int,String,boolean
Town Hall,1,1,4,4,0,Town Hall,
,,2,,,,,
Wall,2,1,1,1,0,Wall,
Cannon,3,1,3,3,0,Defense,
Cannon_gearup,4,1,3,3,0,Defense,
BB Builder Hall,5,1,4,4,1,Town Hall,
BB Army Camp,6,1,3,3,1,Army,
Internal,7,1,0,0,0,Decoration,TRUE
'''
HALLS='''Name,Town Hall,Wall,Cannon,Cannon_gearup,BB Army Camp
String,int,int,int,int,int
1,1,0,1,0,1
2,,25,2,1,2
3,,,3,,
'''


class BuildingDataTests(TestCase):
    def test_name_local_inheritance_and_conditional_limits(self):
        catalog=BuildingCatalog.parse(BUILDINGS,HALLS)
        self.assertEqual(catalog.find('Town Hall').footprint(2),(4,4))
        self.assertEqual(catalog.find('Wall').footprint(1),(1,1))
        self.assertEqual(catalog.find('Army Camp',village=1).footprint(),(3,3))
        self.assertEqual(catalog.upper_limits(2)['Cannon'],2)
        self.assertEqual(catalog.upper_limits(3)['Wall'],25)
        self.assertEqual(catalog.upper_limits(2,village=1),{'BB Army Camp':2,'BB Builder Hall':1})
        self.assertNotIn('Internal',catalog.upper_limits(3))

    def test_bad_tables_and_cross_village_identities_are_rejected(self):
        for buildings,halls in [(BUILDINGS.replace('Wall,2,1,1,1','Wall,2,1,20,1'),HALLS),
             (BUILDINGS.replace('Cannon,3','Wall,3'),HALLS),(BUILDINGS,HALLS.replace('3,,,3,,','4,,,3,,')),
             (BUILDINGS.replace('Internal,7,1,0,0,0','Internal,7,1,0,0,2'),HALLS),
             (BUILDINGS+'orphan\n',HALLS)]:
            with self.subTest(buildings=buildings[-50:],halls=halls[-50:]):
                with self.assertRaises(ValueError):BuildingCatalog.parse(buildings,halls)
        catalog=BuildingCatalog.parse(BUILDINGS,HALLS)
        for village in (True,None,2):
            with self.assertRaises(ValueError):catalog.find('Wall',village=village)
            with self.assertRaises(ValueError):catalog.upper_limits(2,village=village)
        with self.assertRaises(ValueError):catalog.find('Army Camp')
        with self.assertRaises(ValueError):catalog.find('Wall').footprint(2)
