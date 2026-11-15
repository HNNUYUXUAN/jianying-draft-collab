"""Explicit, small Agent Plan acceptance request; durable caches/pending, no automatic retry."""
from pathlib import Path
import json,hashlib,hmac,secrets
from pipeline import config,read,write,sha,audio,assemble,asr

def run(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    receipt=out/'cloud-smoke.json'
    result=read(receipt) if receipt.exists() else {'checks':{},'desktop_actions':0}
    cfg=config()
    # Keep an acceptance run bound to its own account/configuration. This is
    # private local evidence, never a credential or a public configuration file.
    binding_path=out/'account-binding.json'
    credential=(cfg.get('VOLC_AGENT_API_KEY')or'').strip()
    if not credential:raise RuntimeError('Configure this runtime Agent Plan account before cloud acceptance')
    binding=read(binding_path)if binding_path.exists()else{'salt':secrets.token_hex(32)}
    identity=hmac.new(bytes.fromhex(binding['salt']),json.dumps(cfg,sort_keys=True).encode('utf-8'),hashlib.sha256).hexdigest()
    if binding.get('identity')and binding['identity']!=identity:raise RuntimeError('Cloud account or configuration changed; use a new acceptance directory')
    if receipt.exists()and not binding_path.exists():raise RuntimeError('Legacy cloud acceptance is unbound; use a new directory to verify the current account')
    write(binding_path,{**binding,'identity':identity})
    from runtime_env import doctor
    health=doctor(task='offline',required=['core','media','cloud_config'],require_smoke=False)
    if not health['local_ready']:raise RuntimeError('Repair local dependencies before cloud acceptance')
    text='环境检查，配音与字幕正常。'
    manifest=out/'manifest.json'
    if not manifest.exists():write(manifest,{'segments':[{'id':'C01','text':text,'lead_ms':200,'tail_ms':200}]})
    for stage in ('tts','asr','vision'):
        if result['checks'].get(stage,{}).get('status')=='passed':
            result['checks'][stage]['reused_completed_acceptance']=True
            continue
        result['active_stage']=stage;write(receipt,result)
        try:
            if stage=='tts':
                from volc_audio import tts
                path=out/'voice/acceptance.wav'
                # Production shared-cache reuse is useful; an explicit account
                # check instead uses a fresh, run-local TTS request/cache.
                tts(text,path,cfg,cache_root=out/'acceptance-tts-cache')
                info=read(path.with_suffix('.tts.json'));rate,pcm=audio(path)
                from volc_audio import validate_words
                validate_words(info['words'],text,len(pcm)/2/rate*1000)
                detail={'model':cfg['TTS_MODEL'],'sample_rate':rate,'words':len(info['words']),
                        'log_id':info.get('log_id'),'audio':str(path),'timestamp_source':info['timestamp_source'],
                        'evidence':'current-account acceptance request','reused_completed_acceptance':False}
            elif stage=='asr':
                import shutil
                source=Path(result['checks']['tts']['audio'])
                external=out/'external.wav'
                if not external.exists():shutil.copy2(source,external)
                placement=out/'external-placement.json'
                if not placement.exists():write(placement,{'segments':[{'id':'E01','text':text,'audio':str(external),'audio_sha256':sha(external)}]})
                asr(placement,cfg)
                info=read(external.with_suffix('.asr.json'))['response']
                from volc_audio import validate_words
                rate,pcm=audio(external)
                validate_words(info['words'],text,len(pcm)/2/rate*1000)
                detail={'model':cfg['ASR_MODEL'],'input_sample_rate':16000,'words':len(info['words']),
                        'log_id':info.get('log_id'),'timestamp_source':info['timestamp_source']}
            else:
                from PIL import Image,ImageDraw
                image=out/'vision-fixture.png'
                if not image.exists():
                    im=Image.new('RGB',(320,180),'white');draw=ImageDraw.Draw(im)
                    draw.rectangle((90,40,230,140),fill='blue');im.save(image)
                from vision import analyze
                value=analyze([image],'环境连通测试：请用一句话说明图片主体的颜色和形状。',out/'vision')
                texts=[c.get('text','') for o in value.get('output',[]) for c in o.get('content',[]) if c.get('type')=='output_text']
                if not texts:raise ValueError('No vision output text')
                detail={'model':cfg['VISION_MODEL'],'response_id':value.get('id'),'text':' '.join(texts),'image_sha256':sha(image)}
            result['checks'][stage]={'status':'passed',**detail}
        except Exception as e:
            result['checks'][stage]={'status':'failed','error_type':type(e).__name__,'pending_policy':'preserve; no automatic resubmission'}
            write(receipt,result)
            return result
        write(receipt,result)
    result.update(active_stage=None,status='passed');write(receipt,result);return result

if __name__=='__main__':
    import argparse,sys
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    result=run(a.output);print(json.dumps(result,ensure_ascii=False))
    if result.get('status')!='passed':sys.exit(1)
