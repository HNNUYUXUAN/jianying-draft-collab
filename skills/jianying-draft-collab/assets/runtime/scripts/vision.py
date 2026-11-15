"""Agent Plan Responses adapter with durable pending records and no paid retries."""
import base64,json
from pathlib import Path
import requests
from pipeline import read,write,sha,fingerprint,config

def analyze(images,prompt,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);cfg=config()
    model=cfg.get('VISION_MODEL','doubao-seed-2.1-pro');url=cfg.get('VISION_ENDPOINT','https://ark.cn-beijing.volces.com/api/plan/v3/responses')
    if url!='https://ark.cn-beijing.volces.com/api/plan/v3/responses':raise ValueError('Unverified Agent Plan endpoint')
    identity=fingerprint({'model':model,'protocol':1,'prompt':prompt,'images':[sha(f) for f in images]});done=out/(identity+'.json');pending=out/(identity+'.pending.json')
    if done.exists():return read(done)
    if pending.exists():raise ValueError('Uncertain request preserved; reconcile before resubmitting')
    key=cfg.get('VOLC_AGENT_API_KEY');assert key,'Missing dedicated Agent Plan key'
    from PIL import Image
    content=[{'type':'input_text','text':prompt}]
    for f in images:
        with Image.open(f) as im:
            kind=im.format.lower();assert kind in ('png','jpeg');im.verify()
        content.append({'type':'input_image','image_url':'data:image/'+kind+';base64,'+base64.b64encode(Path(f).read_bytes()).decode()})
    write(pending,{'identity':identity,'model':model,'images':len(images),'status':'submitted'})
    with requests.post(url,headers={'Authorization':'Bearer '+key},json={'model':model,'input':[{'role':'user','content':content}],'store':False,'stream':True,'max_output_tokens':5000,'reasoning':{'effort':'low'}},stream=True,timeout=(30,120),allow_redirects=False) as r:
        if r.status_code!=200:raise RuntimeError('Agent Plan HTTP '+str(r.status_code))
        result=None
        for line in r.iter_lines():
            if not line.startswith(b'data:'):continue
            raw=line[5:].strip()
            if raw==b'[DONE]':break
            event=json.loads(raw)
            if event.get('type')=='response.completed':result=event['response'];break
        if not result:raise RuntimeError('Incomplete response; pending retained')
    write(done,result);pending.unlink();return result
