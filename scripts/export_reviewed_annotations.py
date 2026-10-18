"""Export a private pixel-box review batch; never promote AI review to ground truth."""
import argparse
from collections import Counter
import hashlib
import html
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw
from preannotate import load_schema, label_config_xml


def export(batch, schema_path):
    batch = Path(batch).resolve()
    schema = load_schema(schema_path)
    manifest = {row['id']: row for row in json.loads((batch/'manifest.json').read_text())}
    reviews = json.loads((batch/'annotations.json').read_text())
    if len({row['id'] for row in reviews}) != len(reviews):
        raise ValueError('Duplicate review IDs')
    previews = batch/'previews'
    previews.mkdir(exist_ok=True)
    tasks, cards = [], []
    screens, classes = Counter(), Counter()
    corrections = 0
    for review in reviews:
        source = manifest[review['id']]
        image_path = (batch/'images'/source['image']).resolve()
        if not image_path.is_relative_to(batch/'images'):
            raise ValueError('Image must remain inside this batch')
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Image changed after selection: '+source['image'])
        screen = review['screen']
        if screen not in schema['screens']:
            raise ValueError('Unknown screen: '+screen)
        with Image.open(image_path) as original:
            width, height = original.size
            preview = original.convert('RGB')
        draw = ImageDraw.Draw(preview)
        result = [{'id':'screen','from_name':'screen','to_name':'image','type':'choices',
                   'value':{'choices':[screen]}}]
        for index, box in enumerate(review['boxes']):
            label = box['label']
            if label not in schema['_flat_classes']:
                raise ValueError('Unknown object: '+label)
            x, y, bw, bh = box['xywh']
            if (not all(math.isfinite(v) for v in (x,y,bw,bh)) or
                    x < 0 or y < 0 or bw <= 0 or bh <= 0 or x+bw > width or y+bh > height):
                raise ValueError('Invalid box: '+str(box))
            result.append({'id':f'box{index}','from_name':'label','to_name':'image',
                           'type':'rectanglelabels','original_width':width,'original_height':height,
                           'image_rotation':0,'value':{'x':x/width*100,'y':y/height*100,
                           'width':bw/width*100,'height':bh/height*100,'rotation':0,
                           'rectanglelabels':[label]}})
            draw.rectangle((x,y,x+bw,y+bh),outline='#38bdf8',width=4)
            draw.text((x+4,max(0,y-15)),label,fill='#38bdf8',stroke_width=1,stroke_fill='black')
            classes[label] += 1
        preview.save(previews/(Path(source['image']).stem+'.jpg'),quality=92)
        screens[screen] += 1
        corrections += screen != source['suggested_screen']
        task = {'id':source['id'],'data':{
            'image':'/data/local-files/?d=labelstudio/review/'+batch.name+'/images/'+source['image'],
            'session':source['session'],'source_sha256':source['sha256'],
            'suggested_screen':source['suggested_screen'],'reviewer':'AI visual review',
            'human_confirmed':False,'objects_complete':False,'training_ready':False,
            'review_notes':review.get('notes','')},'annotations':[{'result':result}]}
        # Keep layout generations and original provenance through Label Studio
        # round trips. These fields never grant training/human-review approval.
        for key in ('candidate_id', 'source', 'source_group', 'captured_at', 'ui_generation', 'ui_version'):
            if key in source:
                task['data'][key] = source[key]
        task['data']['schema_version'] = schema.get('version')
        tasks.append(task)
        cards.append(f'<article><h2>{source["id"]:02d} · {html.escape(screen)}</h2>'
                     f'<a href="previews/{Path(source["image"]).stem}.jpg"><img '
                     f'src="previews/{Path(source["image"]).stem}.jpg"></a>'
                     f'<p>{html.escape(review.get("notes",""))}</p></article>')
    (batch/'tasks_reviewed.json').write_text(json.dumps(tasks,indent=2))
    (batch/'label_config.xml').write_text(label_config_xml(schema))
    report = {'images':len(tasks),'boxes':sum(classes.values()),'screen_corrections':corrections,
              'screens':dict(screens),'objects':dict(classes),'review_type':'AI visual review',
              'human_confirmed':False,'objects_complete':False,'training_ready':False}
    report['ui_generations'] = dict(Counter(
        task['data'].get('ui_generation', 'unspecified') for task in tasks))
    report['schema_version'] = schema.get('version')
    (batch/'report.json').write_text(json.dumps(report,indent=2))
    (batch/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Annotation review</title>'
        '<style>body{background:#101827;color:#e2e8f0;font:16px system-ui;margin:30px}'
        'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:24px}'
        'img{width:100%}article{background:#1e293b;padding:16px;border-radius:12px}p{color:#a5b4c8}</style>'
        '<h1>Annotation review</h1><p>AI-reviewed draft · partial object labels · human confirmation needed before training.</p>'
        '<main>'+''.join(cards)+'</main>')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--schema',type=Path,default=Path('data/labels.yaml'))
    args = parser.parse_args()
    print(json.dumps(export(args.batch,args.schema),indent=2))
