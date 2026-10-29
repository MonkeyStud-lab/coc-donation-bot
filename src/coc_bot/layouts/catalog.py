"""Only official Home Village layout links can reach the Android importer."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit,parse_qs,urlencode


def official_layout(url, hall):
    if type(hall) is not int or not 2<=hall<=18:
        raise ValueError('A verified Town Hall level from 2 to 18 is required')
    if not isinstance(url,str) or len(url)>300:raise ValueError('Invalid layout link')
    value=urlsplit(url)
    query=parse_qs(value.query,keep_blank_values=True)
    if (value.scheme!='https' or value.netloc!='link.clashofclans.com' or
        value.path not in ('/en','/en/') or value.fragment or
        set(query)!={'action','id'} or query['action']!=['OpenLayout'] or len(query['id'])!=1 or
        not re.fullmatch(r'TH'+str(hall)+r':HV:[A-Za-z0-9_-]{12,100}',query['id'][0])):
        raise ValueError('Use an official Home Village layout link for this account’s Town Hall')
    return 'https://link.clashofclans.com/en/?'+urlencode({'action':'OpenLayout','id':query['id'][0]})


def catalog(hall=None):
    values=json.loads(Path(__file__).with_name('catalog.json').read_text(encoding='utf-8'))
    for entry in values:
        if entry.get('link'):official_layout(entry['link'],entry['hall'])
    return [entry for entry in values if hall is None or entry['hall']==hall]


def placement_plan(blueprint, inventory):
    """Preserve empty footprints for unbuilt structures; never substitute a unit.

    Plans use native 44x44 Home Village tiles, independent of screenshot pixels.
    They do not authorize a drag until the native editor's projection and named
    tray items have been verified. Existing buildings can never be discarded.
    """
    if not isinstance(blueprint,list) or not isinstance(inventory,dict):
        raise ValueError('Verified building inventory and tile blueprint are required')
    remaining=dict(inventory)
    if any(not isinstance(k,str) or type(v) is not int or v<0 for k,v in remaining.items()):
        raise ValueError('Building inventory is invalid')
    occupied=set();placements=[];empty=[]
    for item in blueprint:
        if not isinstance(item,dict) or not isinstance(item.get('name'),str):raise ValueError('Unnamed layout item')
        x,y,w,h=[item.get(k) for k in ('x','y','width','height')]
        if any(type(n) is not int for n in (x,y,w,h)) or not (1<=w<=5 and 1<=h<=5 and 0<=x<=44-w and 0<=y<=44-h):
            raise ValueError('Layout footprint is outside the village')
        tiles={(a,b) for a in range(x,x+w) for b in range(y,y+h)}
        if tiles & occupied:raise ValueError('Layout footprints overlap')
        occupied|=tiles
        name=item['name']
        if remaining.get(name,0)>0:
            placements.append(dict(item));remaining[name]-=1
        else:empty.append(dict(item))
    unplaced={k:v for k,v in remaining.items() if v}
    return {'placements':placements,'empty':empty,'unplaced':unplaced,'complete':not unplaced}
