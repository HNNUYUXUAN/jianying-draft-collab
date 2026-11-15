"""Agent Plan voice transport. No implicit paid retries."""
import asyncio, base64, gzip, hashlib, json, struct, uuid
from pathlib import Path
import requests

TTS_URL='https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional'
ASR_URL='wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_nostream'
DEFAULTS={'FFMPEG_SUBTITLE_BIN':'','VISION_MODEL':'doubao-seed-2.1-pro','VISION_ENDPOINT':'https://ark.cn-beijing.volces.com/api/plan/v3/responses','AUDIO_PROVIDER':'volc_agent_plan','TTS_MODEL':'doubao-seed-tts-2.0',
'TTS_VOICE':'zh_female_vv_uranus_bigtts','TTS_ENDPOINT':TTS_URL,'TTS_RESOURCE_ID':'seed-tts-2.0',
'TTS_NATIVE_SAMPLE_RATE':'24000','TTS_SAMPLE_RATE':'48000','TTS_SPEECH_RATE':'0',
'ASR_MODEL':'doubao-seed-asr-2.0','ASR_ENDPOINT':ASR_URL,
'ASR_RESOURCE_ID':'volc.seedasr.sauc.duration','HTTP_TIMEOUT_SECONDS':'120',
'ASR_MAX_SECONDS':'60','ASR_MAX_BYTES':'9500000','SUBTITLE_MAX_CHARS':'14',
'SUBTITLE_MAX_MS':'5500','SUBTITLE_MIN_MS':'1200','SUBTITLE_GAP_MS':'80'}

def settings(cfg):
    return {**DEFAULTS,**cfg}
def key(cfg):
    value=(cfg.get('VOLC_AGENT_API_KEY') or '').strip()
    if not value: raise ValueError('VOLC_AGENT_API_KEY is empty; no API call made')
    return value
def identity(cfg,kind,source):
    fields=('TTS_ENDPOINT','TTS_RESOURCE_ID','TTS_MODEL','TTS_VOICE','TTS_NATIVE_SAMPLE_RATE','TTS_SAMPLE_RATE','TTS_SPEECH_RATE') if kind=='tts' else ('ASR_ENDPOINT','ASR_RESOURCE_ID','ASR_MODEL')
    return hashlib.sha256(json.dumps({'protocol':1,'provider':'volc_agent_plan','kind':kind,'source':source,
    'options':{k:cfg[k] for k in fields},'word_timestamps':True},sort_keys=True).encode()).hexdigest()
def tts_stream(text,cfg):
    if cfg['TTS_ENDPOINT']!=TTS_URL: raise ValueError('Unsupported Agent Plan TTS endpoint')
    headers={'X-Api-Key':key(cfg),'X-Api-Resource-Id':cfg['TTS_RESOURCE_ID'],'X-Api-Connect-Id':str(uuid.uuid4()),
             'X-Control-Require-Usage-Tokens-Return':'*'}
    body={'req_params':{'text':text,'speaker':cfg['TTS_VOICE'],'audio_params':{
        'format':'wav','sample_rate':int(cfg['TTS_NATIVE_SAMPLE_RATE']),
        'speech_rate':int(cfg['TTS_SPEECH_RATE']),'enable_subtitle':True}}}
    chunks=[]; words=[]; usage=None; done=False
    try:
        with requests.post(TTS_URL,headers=headers,json=body,stream=True,timeout=(20,int(cfg['HTTP_TIMEOUT_SECONDS'])),allow_redirects=False) as r:
            if r.status_code!=200: raise RuntimeError('Agent Plan TTS HTTP '+str(r.status_code))
            logid=r.headers.get('X-Tt-Logid')
            for line in r.iter_lines():
                if not line: continue
                if line.startswith(b'data:'): line=line[5:].strip()
                d=json.loads(line)
                if d.get('data'): chunks.append(base64.b64decode(d['data'],validate=True))
                sentence=d.get('sentence') or {}
                for w in sentence.get('words',[]):
                    words.append({'text':w['word'],'start_ms':round(float(w['startTime'])*1000),
                                  'end_ms':round(float(w['endTime'])*1000)})
                usage=d.get('usage',usage)
                code=d.get('code',0)
                if code==20000000: done=True;break
                if code!=0: raise RuntimeError('Agent Plan TTS service code '+str(code))
            if not done or not chunks: raise RuntimeError('Incomplete TTS; pending retained')
            return b''.join(chunks),{'provider':'volc_agent_plan','timestamp_source':'tts_native',
                                    'words':words,'log_id':logid,'usage':usage}
    except requests.RequestException:
        raise RuntimeError('TTS transport outcome uncertain; pending retained') from None

def packet(kind,seq,payload,final=False):
    data=gzip.compress(payload)
    return bytes([0x11,(kind<<4)|(3 if final else 1),0x11 if kind==1 else 0x01,0])+struct.pack('>iI',-seq if final else seq,len(data))+data
def parse_packet(data):
    if not isinstance(data,bytes) or len(data)<8: raise ValueError('Invalid ASR packet')
    offset=(data[0]&15)*4; kind=data[1]>>4;flags=data[1]&15
    if kind==15: raise RuntimeError('ASR service code '+str(struct.unpack_from('>I',data,offset)[0]))
    if flags&1:offset+=4
    size=struct.unpack_from('>I',data,offset)[0];payload=data[offset+4:offset+4+size]
    if len(payload)!=size:raise ValueError('Truncated ASR packet')
    if data[2]&15==1:payload=gzip.decompress(payload)
    return json.loads(payload),bool(flags&2)
async def recognize(pcm,cfg):
    import websockets
    if cfg['ASR_ENDPOINT']!=ASR_URL:raise ValueError('Unsupported Agent Plan ASR endpoint')
    headers={'X-Api-Key':key(cfg),'X-Api-Resource-Id':cfg['ASR_RESOURCE_ID'],'X-Api-Connect-Id':str(uuid.uuid4())}
    request={'user':{'uid':'jianying-draft-collab'},'audio':{'format':'pcm','codec':'raw','rate':16000,'bits':16,'channel':1},
             'request':{'model_name':'bigmodel','enable_itn':True,'enable_punc':True,'enable_ddc':False,'show_utterances':True,'result_type':'full'}}
    async with websockets.connect(ASR_URL,additional_headers=headers,open_timeout=20,max_size=16*1024*1024) as ws:
        await ws.send(packet(1,1,json.dumps(request).encode()))
        utterances={}
        async def receive():
            while True:
                d,final=parse_packet(await ws.recv())
                if d.get('code',0) not in (0,1000,20000000):raise RuntimeError('ASR service code '+str(d['code']))
                for u in d.get('result',{}).get('utterances',[]):
                    utterances[u.get('start_time')]=u
                if final:
                    words=[{'text':w['text'],'start_ms':w['start_time'],'end_ms':w['end_time']}
                           for _,u in sorted(utterances.items()) for w in u.get('words',[]) if u.get('definite',True)]
                    return {'provider':'volc_agent_plan','timestamp_source':'asr_native','words':words,
                            'log_id':ws.response.headers.get('X-Tt-Logid'),'raw':d}
        task=asyncio.create_task(receive())
        try:
            for i,pos in enumerate(range(0,len(pcm),6400)):
                await ws.send(packet(2,i+2,pcm[pos:pos+6400],pos+6400>=len(pcm)))
                await asyncio.sleep(.2)
            return await asyncio.wait_for(task,int(cfg['HTTP_TIMEOUT_SECONDS']))
        finally:
            if not task.done():task.cancel()
def validate_words(words,text,duration_ms):
    from pipeline import normalized
    if not words or normalized(''.join(w['text'] for w in words))!=normalized(text):raise ValueError('Timestamp transcript mismatch')
    previous=0
    for w in words:
        if not 0<=w['start_ms']<=w['end_ms']<=duration_ms+30 or w['start_ms']<previous:
            raise ValueError('Invalid word timestamp bounds')
        previous=w['start_ms']
    return words
def tts(text,destination,cfg,*,cache_root=None):
    from pipeline import read,write,sha,normalize,audio
    import tempfile
    cfg=settings(cfg);destination=Path(destination);meta=destination.with_suffix('.tts.json');pending=destination.with_suffix('.pending.json')
    ident=identity(cfg,'tts',text)
    if destination.exists() and meta.exists() and read(meta).get('identity')==ident and read(meta).get('sha256')==sha(destination):return
    if destination.exists() or pending.exists():raise ValueError('Existing/uncertain TTS; use explicit recovery or new version')
    cache=(Path(cache_root) if cache_root is not None else Path(__file__).resolve().parents[1]/'cache/voice')/ident
    if (cache/'audio.wav').is_file() and (cache/'meta.json').is_file():
        info=read(cache/'meta.json')
        if info.get('sha256')==sha(cache/'audio.wav'):
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes((cache/'audio.wav').read_bytes());write(meta,info)
            rate,pcm=audio(destination)
            try:
                validate_words(info['words'],text,len(pcm)/2/rate*1000)
                write(destination.with_suffix('.asr.json'),{'audio_sha256':sha(destination),'response':info})
            except ValueError:pass
            return
    key(cfg);destination.parent.mkdir(parents=True,exist_ok=True);write(pending,{'identity':ident,'state':'submitted'})
    cache.mkdir(parents=True,exist_ok=True)
    lock=cache/'pending.json'
    try:
        with lock.open('x',encoding='utf8') as f:json.dump({'identity':ident,'state':'submitted'},f)
    except FileExistsError:raise ValueError('Shared TTS request pending; no duplicate submission')
    blob,info=tts_stream(text,cfg)
    with tempfile.TemporaryDirectory() as td:
        raw=Path(td)/'raw.wav';raw.write_bytes(blob)
        norm=Path(td)/'normalized.wav';normalize(raw,norm,int(cfg['TTS_SAMPLE_RATE']))
        rate,pcm=audio(norm);destination.write_bytes(norm.read_bytes())
    info.update(identity=ident,sha256=sha(destination))
    write(meta,info)
    try:
        validate_words(info['words'],text,len(pcm)/2/rate*1000)
        write(destination.with_suffix('.asr.json'),{'audio_sha256':sha(destination),'response':info})
    except ValueError:pass
    (cache/'audio.wav').write_bytes(destination.read_bytes());write(cache/'meta.json',info)
    lock.unlink()
    pending.unlink()
def asr(placement,cfg):
    from pipeline import read,write,sha,audio,normalize
    import tempfile
    cfg=settings(cfg)
    for item in read(placement)['segments']:
        path=Path(item['audio'])
        if sha(path)!=item['audio_sha256']:raise ValueError('Audio changed since assembly')
        rate,pcm=audio(path);duration=len(pcm)/2/rate
        target=path.with_suffix('.asr.json');pending=path.with_suffix('.asr-pending.json')
        ident=identity(cfg,'asr',sha(path))
        if target.exists():
            stored=read(target)
            if stored.get('audio_sha256')!=sha(path):raise ValueError('Audio cache mismatch')
            if stored.get('response',{}).get('timestamp_source')=='tts_native':
                validate_words(stored['response']['words'],item['text'],duration*1000);continue
            if stored.get('identity')!=ident:raise ValueError('ASR configuration changed; use a new version')
            continue
        if duration>float(cfg['ASR_MAX_SECONDS']):raise ValueError('ASR segment exceeds duration limit')
        if pending.exists():raise ValueError('ASR outcome uncertain; pending retained')
        key(cfg)
        with tempfile.TemporaryDirectory() as td:
            converted=Path(td)/'asr.wav';normalize(path,converted,16000);_,pcm=audio(converted)
        write(pending,{'identity':ident,'state':'submitted'})
        result=asyncio.run(recognize(pcm,cfg))
        write(target,{'identity':ident,'audio_sha256':sha(path),'response':result})
        pending.unlink()
