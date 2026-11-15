"""Invoke the pinned, locally installed music engine; no global skill or network lookup."""
from __future__ import annotations
import hashlib,json,os,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COMMIT='424e7bd1e1f0a328adcd62552145d7172c47e450'

class MusicPlanRequired(ValueError):
    """The agent must supply or revise the music source before production."""

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def identity(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def resolve(path,base):
    value=Path(path)
    return (value if value.is_absolute() else Path(base)/value).resolve()
def example_score_path():return ROOT/'examples/music-smoke-score.json'
def demo_score_path():return ROOT/'examples/music-demo-score.json'

def source_spec(spec=None,base_dir=None):
    """Resolve data paths only. Executable settings belong to the local runtime config."""
    spec=dict(spec or {})
    if spec and set(spec)<={'voice_lufs','music_lufs','duck_db','attack_ms','release_ms','gap_ms'}:
        raise MusicPlanRequired('Legacy mixing-only options require their verified historical cache; select score/file/none for a new render')
    mode=spec.get('mode','score')
    if mode not in ('score','file','none'):raise ValueError('music.mode must be score, file or none')
    allowed={'mode','score','file','sha256','rights','mix'}
    unknown=set(spec)-allowed
    if unknown:raise ValueError('Unknown music fields: '+', '.join(sorted(unknown)))
    result={**spec,'mode':mode}
    key='score' if mode=='score' else 'file' if mode=='file' else None
    if key and spec.get(key):result[key]=str(resolve(spec[key],base_dir or Path.cwd()))
    return result

def plan_ready(spec=None,base_dir=None):
    try:value=source_spec(spec,base_dir)
    except MusicPlanRequired as error:return {'ready':False,'reason':str(error),'spec':{'mode':'score'}}
    key='score' if value['mode']=='score' else 'file' if value['mode']=='file' else None
    if key and not value.get(key):return {'ready':False,'reason':f'Provide music.{key} or explicitly choose music.mode=none','spec':value}
    if key and not Path(value[key]).is_file():return {'ready':False,'reason':f'Music {key} file is missing: '+value[key],'spec':value}
    if key=='score':
        try:project=read(value[key])
        except (ValueError,OSError)as error:return {'ready':False,'reason':'Music score JSON cannot be read: '+str(error),'spec':value}
        if not isinstance(project,dict)or project.get('schema')!='music-production/v1':return {'ready':False,'reason':'Use a music-production/v1 score project','spec':value}
    return {'ready':True,'reason':'Music source selected','spec':value}

def runtime_settings(root=ROOT,overrides=None):
    root=Path(root).resolve();config=root/'runtime-config.json'
    values=dict(read(config).get('music',{})) if config.is_file() else {}
    values.update(overrides or {})
    for key in ('python','engine','config'):
        if not values.get(key):raise RuntimeError(f'Music runtime setting {key} is missing; run bootstrap with music enabled')
        values[key]=str(resolve(values[key],root))
    if values.get('upstream_commit')!=COMMIT:raise RuntimeError('Music engine commit differs from the pinned toolchain')
    return values

def _run(settings,args,timeout=180):
    env={k:v for k,v in os.environ.items() if not any(marker in k.upper()for marker in ('API_KEY','APIKEY','SECRET','TOKEN'))}
    env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
    cmd=[settings['python'],'-X','utf8',str(Path(settings['engine'])/'scripts/studio.py'),*map(str,args)]
    done=subprocess.run(cmd,capture_output=True,timeout=timeout,env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    text=(done.stdout+done.stderr).decode('utf-8',errors='replace')
    if done.returncode:raise RuntimeError('Music engine failed: '+text[-1800:])
    return text

def _engine_files(settings,root):
    lock=read(Path(root)/'music-toolchain.json');engine=Path(settings['engine'])
    if lock['engine']['commit']!=COMMIT:raise RuntimeError('Unexpected music toolchain lock')
    for relative,expected in lock['engine']['files'].items():
        f=engine/relative
        if not f.is_file()or digest(f)!=expected:raise RuntimeError('Music engine source hash mismatch: '+relative)
    return lock['engine']['files']

def doctor(spec=None,*,root=ROOT,runtime_overrides=None):
    """Read-only. Configured sample banks are checked by upstream doctor, without rendering."""
    mode=(spec or {}).get('mode','score')
    if mode in ('none','file'):
        return {'status':'passed','reason':'Selected music source does not require a score renderer','fingerprint':identity({'mode':mode})}
    try:
        settings=runtime_settings(root,runtime_overrides)
        for key in ('python','config'):
            if not Path(settings[key]).is_file():raise RuntimeError('Missing music '+key+': '+settings[key])
        files=_engine_files(settings,root)
        output=_run(settings,['doctor','--config',settings['config']])
        if 'PASS:'not in output:raise RuntimeError('Music doctor returned no successful verification')
        lock=read(Path(root)/'music-toolchain.json')
        expected=f'Python {lock["python"]} NumPy {lock["numpy"]}'
        if output.splitlines()[0].strip()!=expected:raise RuntimeError('Music interpreter/dependency versions differ from the pinned environment: expected '+expected)
        banks=[];validation=None
        if spec and spec.get('score'):
            score=Path(spec['score'])
            if not score.is_file():raise MusicPlanRequired('Score file is missing: '+str(score))
            validation=json.loads(_run(settings,['validate',score]))
            if validation.get('warnings'):raise MusicPlanRequired('Score validation warnings: '+json.dumps(validation['warnings'],ensure_ascii=False))
            project=read(score)
            banks=sorted({t.get('soundfont','default')for t in project['tracks']if t.get('engine','soundfont')=='soundfont'})
            configured=read(settings['config'])
            for bank in banks:
                if bank!='default'and bank not in configured.get('soundfonts',{}):raise RuntimeError('Required music sample bank is not configured: '+bank)
        fingerprint=identity({'python':digest(settings['python']),'engine_files':files,'configuration':digest(settings['config']),'commit':COMMIT})
        return {'status':'passed','reason':'Pinned music engine, tools and sample banks verified','fingerprint':fingerprint,'sample_banks':banks,'score_validation':validation,'upstream_commit':COMMIT,'api_called':False}
    except Exception as error:
        return {'status':'failed','reason':str(error),'fingerprint':None,'error_type':type(error).__name__,'api_called':False}

def prepare_score(score,out,*,root=ROOT,runtime_overrides=None):
    score=Path(score).resolve();out=Path(out).resolve()
    check=doctor({'mode':'score','score':str(score)},root=root,runtime_overrides=runtime_overrides)
    if check['status']!='passed':raise RuntimeError(check['reason'])
    settings=runtime_settings(root,runtime_overrides)
    key=identity({'score':digest(score),'runtime':check['fingerprint']})
    review=out/('review-'+key[:16])
    out.mkdir(parents=True,exist_ok=True)
    if not (review/'score_review.json').is_file():_run(settings,['review',score,'--config',settings['config'],'--output',review,'--json'])
    questions=read(review/'score_review.json').get('questions',[])
    if questions:raise MusicPlanRequired('Review and resolve the score questions in '+str(review/'score_review.json'))
    return {'identity':key,'settings':settings,'runtime_fingerprint':check['fingerprint'],'review':str(review),'validation':check.get('score_validation')}

def render_score(score,out,*,root=ROOT,runtime_overrides=None):
    score=Path(score).resolve();out=Path(out).resolve()
    prepared=prepare_score(score,out,root=root,runtime_overrides=runtime_overrides)
    key=prepared['identity'];settings=prepared['settings']
    render=out/('render-'+key[:16]);receipt=out/('adapter-'+key[:16]+'.json')
    if receipt.is_file():
        old=read(receipt)
        if old.get('identity')==key and (render/'master.wav').is_file()and digest(render/'master.wav')==old.get('master_sha256'):
            return {**old,'master':str(render/'master.wav'),'render':str(render),'cache_hit':True}
    request=out/('render-'+key[:16]+'.request.json')
    resume=render.exists()
    if resume and(not request.is_file()or read(request).get('identity')!=key):raise RuntimeError('An unrecorded music render exists; inspect it before resuming: '+str(render))
    request.write_text(json.dumps({'identity':key,'score_sha256':digest(score)},indent=2),encoding='utf-8')
    args=['render',score,'--config',settings['config'],'--output',render,'--jobs','1','--json']
    if resume:args.append('--resume')
    _run(settings,args,timeout=1800)
    report=read(render/'report.json')
    if report.get('draft')or not report.get('checks')or not all(report['checks'].values()):raise RuntimeError('Music renderer delivery checks did not pass')
    result={'identity':key,'score_sha256':digest(score),'runtime_fingerprint':prepared['runtime_fingerprint'],'upstream_commit':COMMIT,'master_sha256':digest(render/'master.wav'),'technical_status':report['status'],'audition':'pending listener feedback','cache_hit':False}
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {**result,'master':str(render/'master.wav'),'render':str(render)}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('command',choices=['doctor']);p.add_argument('--score');p.add_argument('--root',default=str(ROOT));a=p.parse_args()
    result=doctor({'mode':'score',**({'score':a.score}if a.score else{})},root=a.root)
    print(json.dumps(result,ensure_ascii=False));sys.exit(0 if result['status']=='passed'else 1)
