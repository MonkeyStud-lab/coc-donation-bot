"""Use native import residuals, not Hall-level guesses, to check building fit.

An import with enabled Save fits the actual owned inventory. For incomplete
copies a small, independently stable inventory qualifies for bounded placement.
A known prefix followed by unknown cards permits only a six-placement trial;
native completion remains mandatory, and unknown cards are never guessed.
"""
from coc_bot.layouts.placement import InventoryPlacer,tray_boxes,tray_item,same_art
from coc_bot.stop import interrupted_sleep

MAX_REMAINDER=6


def page(reader,frame):
    if not reader.editing(frame):return None
    boxes=tray_boxes(frame)
    if not boxes:return None
    items=[tray_item(reader,frame,n) for n in range(len(boxes))]
    if any(item is None for item in items):return None
    return items


def equal_page(a,b):
    return bool(a and b and len(a)==len(b) and all(
        same_art(x,y) and x['count']==y['count'] and x['point']==y['point']
        for x,y in zip(a,b)))


def excessive_prefix(reader,first,second):
    """A proved excess is enough to reject; unreadable later art is irrelevant."""
    if not reader.editing(first) or not reader.editing(second):return None
    total=0
    for slot in range(min(len(tray_boxes(first)),len(tray_boxes(second)))):
        a=tray_item(reader,first,slot);b=tray_item(reader,second,slot)
        if not same_art(a,b) or a['count']!=b['count']:break
        total+=a['count']
        if total>MAX_REMAINDER:return total
    return None


def bounded_prefix(reader,first,second):
    """A small known prefix permits a capped inactive trial, not activation.

    Decorations may follow the required buildings. Do not invent their type,
    count, or optionality; only native Save can prove the trial is complete.
    """
    if not reader.editing(first) or not reader.editing(second):return None
    total=0
    for slot in range(min(len(tray_boxes(first)),len(tray_boxes(second)))):
        a=tray_item(reader,first,slot);b=tray_item(reader,second,slot)
        if not same_art(a,b) or a['count']!=b['count'] or a['point']!=b['point']:break
        total+=a['count']
        if total>MAX_REMAINDER:return None
    if not total:return None
    return {'count':total,'small':False,'probe':True,'complete_count':False,
            'method':'bounded_native_trial'}


def assess_remaining(importer):
    """No building drags or purchases; swipe only the verified inventory tray."""
    placer=InventoryPlacer(importer)
    placer.check_owner()
    if not placer.reset_inventory() or importer.stop():return None
    f=importer.s.capture.screenshot();fresh=importer.s.capture.screenshot()
    excess=excessive_prefix(importer.reader,f,fresh)
    if excess is not None:
        return {'count':excess,'small':False,'complete_count':False,'method':'native_remaining_inventory'}
    a=page(importer.reader,f);b=page(importer.reader,fresh)
    if not equal_page(a,b):return bounded_prefix(importer.reader,f,fresh)
    count=sum(v['count'] for v in a)
    if count>MAX_REMAINDER:
        return {'count':count,'small':False,'complete_count':False,'method':'native_remaining_inventory'}
    # Prove the entire tray fits on one page. Hidden extra defenses must not
    # become a small fallback because only the first six cards were visible.
    h,w=f.shape[:2]
    if importer.stop():return None
    importer.s.input.swipe(round(w*.83),round(h*.975),round(w*.17),round(h*.975),450)
    if interrupted_sleep(.25,importer.stop):return None
    c=page(importer.reader,importer.s.capture.screenshot())
    d=page(importer.reader,importer.s.capture.screenshot())
    if not equal_page(c,d):return None
    full=equal_page(a,c)
    return {'count':count,'small':full,'probe':not full,'complete_count':full,'method':'native_remaining_inventory',
            'items':[{'level':v['level'],'count':v['count'],'wall':v['wall']} for v in a]}
