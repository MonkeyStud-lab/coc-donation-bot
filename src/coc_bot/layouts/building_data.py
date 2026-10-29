"""Factual construction metadata, independent of screenshots and spending.

Bundled asset versions and Android package versions are recorded separately.
Neither an APK table nor a remembered Hall level authorizes a game action.
"""
from dataclasses import dataclass, field
import csv
import io
import re


def key(name):
    if not isinstance(name,str) or not name.strip():
        raise ValueError('A building name is required')
    return re.sub(r'[^a-z0-9]', '', name.lower())


def rows(value, required):
    if not isinstance(value,str) or len(value)>10_000_000:
        raise ValueError('Invalid static table text')
    reader=csv.DictReader(io.StringIO(value),strict=True)
    if (not required<=set(reader.fieldnames or []) or
        len(reader.fieldnames)!=len(set(reader.fieldnames))):
        raise ValueError('Static table schema changed')
    for index,row in enumerate(reader):
        if index>=5000 or None in row or None in row.values():
            raise ValueError('Invalid static table record')
        yield row


@dataclass
class Building:
    name: str
    global_id: int
    village: int
    category: str
    hidden: bool = False
    levels: dict[int, tuple[int, int]] = field(default_factory=dict)

    def footprint(self, level=None):
        if level is None:
            if not self.levels:
                raise ValueError('No verified building footprint')
            return max(v[0] for v in self.levels.values()), max(v[1] for v in self.levels.values())
        if type(level) is not int or level not in self.levels:
            raise ValueError('Building level is absent from this asset revision')
        return self.levels[level]


class BuildingCatalog:
    def __init__(self, buildings, limits):
        self.buildings = buildings
        self.limits = limits

    @classmethod
    def parse(cls, buildings_csv, halls_csv):
        required = {'Name','GlobalID','BuildingLevel','Width','Height','VillageType','BuildingClass'}
        result = {}; current = None; inherited = {}
        for row in rows(buildings_csv,required):
            if row['GlobalID'] == 'int' and row['Width'] == 'int':
                continue  # The native CSV has an explicit column-type row.
            if row['Name']:
                if row['Name'] in result or not row['GlobalID'].isdigit():
                    raise ValueError('Duplicate or invalid building identity')
                inherited = {k:v for k,v in row.items() if v != ''}
                village = int(row['VillageType'] or '0')
                if village not in (0,1):
                    raise ValueError('Unsupported village type')
                current = Building(row['Name'], int(row['GlobalID']), village,
                                   row['BuildingClass'], row.get('Hidden') == 'TRUE')
                result[current.name] = current
            elif current is None:
                raise ValueError('Building level has no object identity')
            else:
                inherited.update({k:v for k,v in row.items() if v != ''})
            if not row['BuildingLevel']:
                continue  # Extra array entries do not create another level.
            level = int(row['BuildingLevel'])
            width, height = int(inherited.get('Width','0')), int(inherited.get('Height','0'))
            if not 1 <= level <= 100 or not 0 <= width <= 8 or not 0 <= height <= 8:
                raise ValueError('Invalid building level or dimensions')
            if width == 0 or height == 0:
                continue  # Non-placeable internal objects have no tile footprint.
            previous = current.levels.get(level)
            if previous is not None and previous != (width,height):
                raise ValueError('Conflicting footprints for one building level')
            current.levels[level] = width,height
        if 'Town Hall' not in result or 'Wall' not in result:
            raise ValueError('Required Home Village definitions are missing')
        inherited = {}; limits = {}
        for row in rows(halls_csv,{'Name'}):
            if row['Name'].lower() in ('int','string'):
                continue
            if not row['Name'].isdigit():
                raise ValueError('Invalid Town Hall identity')
            hall = int(row['Name'])
            if not 1 <= hall <= 30 or hall in limits:
                raise ValueError('Duplicate or unsupported Town Hall level')
            for name in result:
                if row.get(name):
                    value = int(row[name])
                    if not 0 <= value <= 1000:
                        raise ValueError('Invalid building count')
                    inherited[name] = value
            limits[hall] = dict(inherited)
        if not limits or sorted(limits) != list(range(1,max(limits)+1)):
            raise ValueError('Town Hall limits are incomplete')
        return cls(result, limits)

    def find(self, name, *, village=0):
        if type(village) is not int or village not in (0,1):
            raise ValueError('Unsupported village')
        normalized = key(name)
        aliases = ({'workshop':'siegeworkshop'} if village == 0 else
                   {'builderbarracks':'barracks','builderhall':'builderhall'})
        normalized = aliases.get(normalized, normalized)
        found = [b for b in self.buildings.values() if b.village == village
                 and key(b.name.removeprefix('BB ') if village else b.name) == normalized]
        if len(found) != 1:
            raise ValueError('Building identity is unknown or ambiguous')
        return found[0]

    def upper_limits(self, hall, *, village=0):
        """Conditional asset limits, never a required or owned inventory.

        Merged defenses and their consumed predecessors can both have limits.
        Builder Huts may require gems. Native ownership/unlocks must therefore
        be read separately before reserving or placing any building.
        """
        if (type(hall) is not int or hall not in self.limits or
            type(village) is not int or village not in (0,1)):
            raise ValueError('Unsupported village or Hall level')
        values = {}
        for name, amount in self.limits[hall].items():
            building = self.buildings[name]
            if building.village != village or building.hidden or not building.levels or not amount:
                continue
            # A geared-up defense is an alternate version of an existing
            # Cannon/Tower/Mortar, not an extra building to place beside it.
            display = name.removesuffix('_gearup')
            values[display] = max(values.get(display,0),amount)
        values['Town Hall' if village == 0 else 'BB Builder Hall'] = 1
        return values
