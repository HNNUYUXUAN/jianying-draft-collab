"""Deterministic real-footage production. Host Agent supplies evidence-based plan/images."""
import argparse,json,subprocess,shutil,math,wave,hashlib
from pathlib import Path
from pipeline import read,write,sha,fingerprint,config,assemble,align,asr
from visual_assets import audit_images

def ff(args):subprocess.run(['ffmpeg','-v','error','-nostdin','-y',*map(str,args)],check=True)
def probe(path):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
def subtitle_ffmpeg():
    candidates=[Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe']
    for f in candidates:
        if not f or not Path(f).is_file():continue
        r=subprocess.run([str(f),'-hide_banner','-h','filter=subtitles'],capture_output=True)
        if b'force_style' in r.stdout+r.stderr:return str(f)
    raise RuntimeError('Dedicated full FFmpeg with libass is missing; run skill bootstrap.ps1 -Repair.')
def hlg_to_709_filter(path):
    stream=next(s for s in probe(path)['streams'] if s['codec_type']=='video')
    if stream.get('color_transfer')!='arib-std-b67':return ''
    expected={'color_primaries':'bt2020','color_space':'bt2020nc','color_range':'tv'}
    if any(stream.get(k)!=v for k,v in expected.items()):
        raise ValueError('HLG conversion requires verified BT.2020 non-constant limited-range input tags')
    return 'zscale=primariesin=bt2020:transferin=arib-std-b67:matrixin=bt2020nc:rangein=limited:transfer=linear:npl=100,format=gbrpf32le,tonemap=tonemap=hable:desat=0,zscale=primaries=bt709:transfer=bt709:matrix=bt709:range=limited,format=yuv420p'
def prepare(inputs,project):
    from runtime_env import preflight
    readiness=preflight(task='prepare',music={'mode':'score'})
    if not readiness['ready']:raise RuntimeError('Environment incomplete: '+', '.join(map(str,readiness['failed']))+'; prepare the local capabilities before extracting project media')
    p=Path(project).resolve();p.mkdir(parents=True,exist_ok=False);(p/'engineering').mkdir();sources=[]
    for i,item in enumerate(inputs,1):
        f=Path(item).resolve();info=probe(f);sid=f'S{i:03}';video=next(s for s in info['streams'] if s['codec_type']=='video')
        subprocess.run(['ffmpeg','-v','error','-threads','2','-i',str(f),'-f','null','-'],check=True,capture_output=True)
        row={'id':sid,'path':str(f),'sha256':sha(f),'duration_us':round(float(info['format']['duration'])*1e6),'width':video['width'],'height':video['height']};sources.append(row)
        frames=json.loads(subprocess.check_output(['ffprobe','-v','error','-threads','2','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(f)]));write(p/'engineering'/f'{sid}-frame-pts.json',frames)
        ff(['-threads','2','-i',f,'-vf','fps=1/4,scale=960:-2:out_range=full','-pix_fmt','yuvj420p','-map_metadata','-1',p/'engineering'/f'{sid}-%03d.jpg'])
        for label,time in [('head',0),('tail',max(0,row['duration_us']/1e6-.08))]:
            ff(['-threads','2','-ss',time,'-i',f,'-frames:v','1','-vf','scale=960:-2:out_range=full','-pix_fmt','yuvj420p','-map_metadata','-1',p/'engineering'/f'{sid}-{label}.jpg'])
    write(p/'sources.json',sources);write(p/'state.json',{'stage':'prepared','needs':'Agent: evidence-based duration, observations, production-plan.json, music score and verified image assets','defaults':{'fps':60,'music':{'mode':'score'},'image_lane':'web_chatgpt'}});return status(p)
def status(p):return read(Path(p)/'state.json')
def validate_plan(plan,sources):
    assert plan.get('version')==1
    rows=plan['segments'];assert rows and len({r['id'] for r in rows})==len(rows)
    limits=plan.get('duration_range_seconds')
    duration=sum(r['frames']for r in rows)/plan.get('fps',60)
    assert duration>0
    if limits is not None:
        assert isinstance(limits,(list,tuple)) and len(limits)==2
        assert all(type(v) in (int,float) and math.isfinite(v) for v in limits)
        assert 0<limits[0]<=limits[1]
        assert limits[0]<=duration<=limits[1]
    for r in rows:
        assert type(r['frames']) is int and r['frames']>0
        assert bool(r.get('source_id'))!=bool(r.get('image_id'))
        if r.get('source_id'):
            s=sources[r['source_id']];assert 0<=r.get('source_start_us',0)<s['duration_us']
            assert r.get('speed',1)>0
            assert r.get('source_start_us',0)<r.get('source_end_us',s['duration_us'])<=s['duration_us']
            required=r['frames']/plan.get('fps',60)*1e6*r.get('speed',1)
            assert r.get('hold_tail') or r.get('source_start_us',0)+required<=r.get('source_end_us',s['duration_us'])
    return rows
def build(project):
    p=Path(project).resolve();eng=p/'engineering';plan=read(p/'production-plan.json');sources={s['id']:s for s in read(p/'sources.json')};rows=validate_plan(plan,sources)
    from music import legacy_cache,request_identity
    from music_adapter import plan_ready,MusicPlanRequired
    # Work out the existing voice-cache identity before any paid request. A legacy
    # music cache is accepted only against that actual, already cached narration.
    fps=plan.get('fps',60)
    manifest={'segments':[{'id':r['id'],'text':r['text'],'slot_ms':r['frames']/fps*1000,'lead_ms':r.get('lead_ms',350),'tail_ms':r.get('tail_ms',250)} for r in rows]}
    cfg=config();cfg['SUBTITLE_MAX_CHARS']='14'
    voice=eng/('voice-'+fingerprint({'manifest':manifest,'config':{k:v for k,v in cfg.items() if 'KEY' not in k and 'SECRET' not in k}})[:12])
    music_options=plan.get('music');legacy=None
    if (voice/'continuous.wav').is_file()and (voice/'caption-report.json').is_file():
        legacy=legacy_cache(voice/'continuous.wav',read(voice/'caption-report.json').get('cues',[]),eng/'music',music_options)
    if legacy:music_spec={'mode':'none'};music_identity='legacy:'+legacy['identity']
    else:
        ready=plan_ready(music_options,p)
        if not ready['ready']:
            write(p/'state.json',{'stage':'needs_music_plan','reason':ready['reason'],'action':'Author a scene-appropriate score or choose file/none, then resume; narration synthesis has not started'})
            return status(p)
        music_spec=ready['spec'];music_identity=request_identity(music_spec,base_dir=p)
    nr=eng/'native.json'
    if (p/'delivery/剪映草稿').exists():
        previous=read(nr)if nr.is_file()else{}
        if previous.get('music_identity')!=music_identity and not legacy:
            raise ValueError('Music source or implementation changed for an existing native draft. Create a new project version; preserve the saved timeline and reuse unchanged voice/video caches.')
    from runtime_env import preflight as task_preflight
    expected_voice_state={'manifest_sha256':hashlib.sha256(json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')).hexdigest(),
        'config':fingerprint({k:v for k,v in cfg.items() if 'KEY' not in k and 'SECRET' not in k})}
    cached_voice=all((voice/name).is_file()for name in ('continuous.wav','caption-report.json','captions.srt','assembly-state.json'))and read(voice/'assembly-state.json')==expected_voice_state
    required=['core','media','font','music','native']if cached_voice else None
    preflight=task_preflight(p,task='video',music=music_spec,required=required)
    if not preflight['ready']:raise RuntimeError('Environment incomplete: '+', '.join(map(str,preflight['failed']))+'; repair the reported capabilities before production')
    if music_spec['mode']=='score':
        from music_adapter import prepare_score
        try:
            prepared_score=prepare_score(music_spec['score'],eng/'music/score')
            if abs(prepared_score['validation']['seconds']-sum(r['frames']for r in rows)/fps)>1/48000:
                raise MusicPlanRequired('Revise the score form and tail to match the planned picture duration before narration synthesis')
        except MusicPlanRequired as error:
            write(p/'state.json',{'stage':'needs_music_plan','reason':str(error),'action':'Resolve the score review before narration synthesis, then resume'})
            return status(p)
    subtitle_ffmpeg()  # Check local capabilities before any paid synthesis.
    for s in sources.values():assert sha(s['path'])==s['sha256'],'Source changed'
    images=plan.get('images',{});missing=[r['image_id'] for r in rows if r.get('image_id') and r['image_id'] not in images]
    if missing:write(p/'state.json',{'stage':'needs_images','image_ids':missing});return status(p)
    for key,img in images.items():
        assert img['qa']=={'facts':'passed','text':'passed','visual':'passed'}
        assert sha(p/img['path'])==img['sha256']
    try:
        image_audit=audit_images(p,plan,sources)
    except ValueError as error:
        write(p/'state.json',{'stage':'needs_image_audit','reason':str(error),'action':'Complete Chrome Create image provenance and static-page usage; run video audit-images'})
        return status(p)
    write(eng/'image-audit.json',image_audit)
    eng.mkdir(exist_ok=True);assert 48000%fps==0
    manifest_path=eng/'narration.json';write(manifest_path,manifest)
    write(p/'state.json',{'stage':'synthesizing','voice':str(voice)})
    placement=assemble(manifest_path,voice,cfg,synthesize=True,resume=voice.exists())
    if not (voice/'captions.srt').exists():
        asr(placement,cfg)  # Reuses validated TTS words; external ASR only when necessary.
        align(placement,cfg)
    report=read(voice/'caption-report.json')
    if plan.get('caption_phrases'):
        from captions import reflow
        from pipeline import stamp
        cues=reflow(read(placement),read(voice/'alignment-audit.json'),plan['caption_phrases'])
        (voice/'captions.srt').write_text('\n\n'.join(f'{i}\n{stamp(c["start_ms"])} --> {stamp(c["end_ms"])}\n{c["text"]}' for i,c in enumerate(cues,1))+'\n',encoding='utf-8-sig')
        write(voice/'caption-report.json',{'cues':cues,'warnings':[],'reviewed_semantic_boundaries':True})
    else:
        cues=report['cues']
        if report.get('warnings') and not plan.get('caption_reviewed'):
            write(p/'state.json',{'stage':'needs_caption_review','report':str(voice/'caption-report.json'),'action':'Agent reviews clauses; set caption_phrases or caption_reviewed, then resume'})
            return status(p)
    assert all(len(c['text'])<=14 for c in cues)
    out=p/'delivery';package=out/'剪映导入包'
    for name in ['video','audio','images','subtitles']:(package/name).mkdir(parents=True,exist_ok=True)
    from music import create
    try:music=create(voice/'continuous.wav',cues,eng/'music',music_options if legacy else music_spec,base_dir=p)
    except MusicPlanRequired as error:
        write(p/'state.json',{'stage':'needs_music_plan','reason':str(error),'action':'Revise the score/source; completed narration remains cached for resume'})
        return status(p)
    for source,dest in [('dialogue.wav','旁白.wav'),('bgm.wav','音乐.wav'),('mix.wav','混音.wav')]:shutil.copy2(eng/'music'/source,package/'audio'/dest)
    shutil.copy2(voice/'captions.srt',package/'subtitles/captions.srt');write(package/'subtitles/cues.json',cues)
    write(p/'state.json',{'stage':'rendering','voice':str(voice)})
    cursor=0;visuals=[]
    for number,r in enumerate(rows,1):
        dest=package/'video'/f'{number:02}-{r["id"]}.mp4';signature=fingerprint({'render_profile':'contain-1080p-hlg709-v2','row':r,'source':sources.get(r.get('source_id')),'image':images.get(r.get('image_id'))});receipt=eng/(r['id']+'.render.json')
        if not (receipt.exists() and dest.exists() and read(receipt).get('signature')==signature and read(receipt).get('sha256')==sha(dest)):
            if r.get('image_id'):
                im=images[r['image_id']];source=p/im['path'];args=['-loop','1','-i',source];vf='scale=1690:950:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:white,fps='+str(fps);shutil.copy2(source,package/'images'/(r['image_id']+source.suffix))
            else:
                source=sources[r['source_id']]['path'];args=['-threads','2','-ss',r.get('source_start_us',0)/1e6,'-i',source];vf=f"trim=duration={(r.get('source_end_us',sources[r['source_id']]['duration_us'])-r.get('source_start_us',0))/1e6},setpts=(PTS-STARTPTS)/{r.get('speed',1)},scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:white,setsar=1,fps={fps}"
                color_filter=hlg_to_709_filter(source)
                if color_filter:vf=vf.replace(',pad=',','+color_filter+',pad=',1)
                if r.get('hold_tail'):vf+=f',tpad=stop_mode=clone:stop_duration={r["frames"]/fps}'
                if r.get('speed',1)!=1:vf+=",drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='"+str(r['speed'])+"x':x=80:y=80:fontsize=50:fontcolor=white:box=1:boxcolor=black@0.5"
            ff([*args,'-vf',vf,'-frames:v',r['frames'],'-an','-c:v','libx264','-preset','fast','-crf','20','-threads','2','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv','-map_metadata','-1',dest]);write(receipt,{'signature':signature,'sha256':sha(dest)})
        start=round(cursor/fps*1e6);cursor+=r['frames'];visuals.append({'id':r['id'],'path':str(dest.relative_to(package)).replace('\\','/'),'start_us':start,'duration_us':round(cursor/fps*1e6)-start,'volume':0})
    total=round(cursor/fps*1e6)
    draft={'schema_version':2,'project':{'width':1920,'height':1080,'fps':fps},'tracks':[{'id':'picture','type':'video','segments':visuals}]}
    for name,file in [('narration','旁白.wav'),('music','音乐.wav')]:draft['tracks'].append({'id':name,'type':'audio','segments':[{'id':name+'01','path':'audio/'+file,'start_us':0,'duration_us':total,'volume':1}]})
    draft['tracks'].append({'id':'captions','type':'text','segments':[{'id':f'C{i:03}','text':c['display_text'],'start_us':c['start_ms']*1000,'duration_us':(c['end_ms']-c['start_ms'])*1000,'style':{'size':7,'align':1},'clip_settings':{'transform_y':-.85},'border':{'color':[0,0,0],'width':20}} for i,c in enumerate(cues)]});write(package/'draft-plan.json',draft)
    timeline={'fps':fps,'total_frames':cursor,'duration_us':total,'sources':list(sources.values()),'segments':rows,'visuals':visuals,'cues':cues};write(package/'timeline.json',timeline)
    preview=out/'完整预览.mp4';signature=fingerprint({'draft':draft,'visuals':[sha(package/v['path']) for v in visuals],'mix':sha(package/'audio/混音.wav')});pr=eng/'preview.json'
    picture_signature=fingerprint({'visuals':[(v,sha(package/v['path'])) for v in visuals],'cues':cues})
    if not (pr.exists() and preview.exists() and read(pr).get('signature')==signature):
        if pr.exists() and preview.exists() and read(pr).get('picture_signature')==picture_signature:
            temp=eng/'remux.mp4'
            ff(['-i',preview,'-i',package/'audio/混音.wav','-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-map_metadata','-1',temp])
            temp.replace(preview);write(pr,{'signature':signature,'picture_signature':picture_signature})
        else:
            (eng/'concat.txt').write_text('\n'.join("file '"+(package/v['path']).as_posix()+"'" for v in visuals)+'\n',encoding='utf-8')
            ff(['-f','concat','-safe','0','-i',eng/'concat.txt','-i',package/'audio/混音.wav','-c:v','copy','-c:a','aac','-map_metadata','-1',eng/'preview-clean.mp4'])
            shutil.copy2(package/'subtitles/captions.srt',eng/'preview.srt')
            subprocess.run([subtitle_ffmpeg(),'-v','error','-nostdin','-y','-i','preview-clean.mp4','-vf',"subtitles=preview.srt:force_style='FontName=Microsoft YaHei,FontSize=20,Outline=1,MarginV=22'",'-c:v','libx264','-preset','fast','-crf','20','-threads','2','-c:a','copy','-map_metadata','-1',str(preview)],cwd=eng,check=True);write(pr,{'signature':signature,'picture_signature':picture_signature})
    import draft_backend as b
    from native_bridge import normalize_created
    native=out/'剪映草稿';identity=fingerprint(draft);nr=eng/'native.json'
    if not (native.exists() and nr.exists() and read(nr)['identity']==identity):
        if native.exists():raise ValueError('Draft changed: use a new project version; existing draft preserved')
        c=b.build(draft,package);app=b.app_dir();destination=b.DEFAULT_PROJECTS/plan.get('draft_name',p.name)
        b.stage(c,native,destination,None,app);receipt=read(native/'batch-receipt.json');receipt.update(backend='bundled_lyra',state='validated',native_validation=normalize_created(native,app,1920,1080));write(native/'batch-receipt.json',receipt);write(nr,{'identity':identity,'music_identity':music_identity})
    registration={'registered':False,'reason':'application running'}
    if not b.running():
        destination=Path(read(native/'batch-receipt.json')['destination'])
        if destination.exists():
            assert read(destination/'draft_meta_info.json')['draft_id']==read(native/'draft_meta_info.json')['draft_id'],'Registration conflict'
            registration={'registered':True,'destination':str(destination)}
        else:registration=b.install(native,b.DEFAULT_PROJECTS,b.app_dir())
    write(p/'state.json',{'stage':'built','import_package':str(package),'draft':str(native),'preview':str(preview),'duration_us':total,'registration':registration,'in_app_playback':'pending user verification'});return validate(p)
def validate(project):
    p=Path(project);package=p/'delivery/剪映导入包';d=read(package/'draft-plan.json');t=read(package/'timeline.json')
    from draft_backend import validate as check,build as generate,app_dir
    from native_bridge import validate as native_check
    file_result=check(generate(d,package));n=t['total_frames'];fps=t['fps']
    for v in t['visuals']:
        stream=next(s for s in probe(package/v['path'])['streams'] if s['codec_type']=='video');assert int(stream['nb_frames'])==round(v['duration_us']*fps/1e6)
    for name in ['旁白.wav','音乐.wav','混音.wav']:
        with wave.open(str(package/'audio'/name)) as w:assert w.getnframes()==n*48000//fps
    for c in t['cues']:assert c['display_text']==c['text'] and c['text'] and len(c['text'])<=14
    for s in t['sources']:assert sha(s['path'])==s['sha256']
    report={'file_checks':file_result,'native':native_check(p/'delivery/剪映草稿',app_dir()),'source_unchanged':True,'in_app_playback':'pending user','desktop_actions':0};write(p/'engineering/validation.json',report);return report
def main():
    a=argparse.ArgumentParser();a.add_argument('command',choices=['prepare','build','resume','status','validate','audit-images']);a.add_argument('--project',required=True);a.add_argument('--inputs',nargs='+');a.add_argument('--images-only',action='store_true');x=a.parse_args()
    if x.images_only and x.command!='audit-images':a.error('--images-only is only supported by audit-images')
    result=audit_images(x.project,images_only=x.images_only) if x.command=='audit-images' else prepare(x.inputs,x.project) if x.command=='prepare' else status(x.project) if x.command=='status' else validate(x.project) if x.command=='validate' else build(x.project)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
