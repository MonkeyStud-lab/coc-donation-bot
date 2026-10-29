"""General-purpose air reinforcements for open requests, sized by live capacity."""
from collections import Counter

HOUSING={'electro_dragon':30,'dragon':20,'baby_dragon':10,'balloon':5,'wizard':4,'minion':2,'archer':1}
COMPOSITIONS={10:('balloon',)*2,15:('baby_dragon','balloon'),20:('dragon',),
              25:('dragon','balloon'),30:('electro_dragon',),35:('electro_dragon','balloon'),
              40:('dragon','dragon'),45:('dragon','dragon','balloon'),
              50:('electro_dragon','dragon'),55:('electro_dragon','dragon','balloon')}


def composition(space, available):
    available=set(available)&HOUSING.keys()
    desired=COMPOSITIONS.get(space)
    if desired and set(desired)<=available:return Counter(desired)
    # Partly filled castles and missing/unlocked units use an exact-space DP.
    # Prefer substantial air troops; leave an unfillable gap rather than junk.
    plans={0:()}
    for used in range(max(0,space)+1):
        if used not in plans:continue
        for unit in HOUSING:
            if unit=='archer':continue
            target=used+HOUSING[unit]
            if unit not in available or target>space:continue
            candidate=plans[used]+(unit,)
            score=lambda p:(sum(HOUSING[u]**2 for u in p),-len(p))
            if target not in plans or score(candidate)>score(plans[target]):plans[target]=candidate
    filled=max(plans);result=Counter(plans[filled]);gap=space-filled
    if 'archer' in available and 0<gap<=3:result['archer']=gap
    return result
