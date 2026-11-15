"""Batch draft file backend. Live documents are never edited."""
import argparse, copy, hashlib, json, os, shutil, sys, tempfile, time, uuid
from pathlib import Path
from pipeline import read,write,sha
ROOT=Path(__file__).resolve().parents[1]
from native_runtime import projects_root
DEFAULT_PROJECTS=projects_root()
def app_dir():
    from native_runtime import resolve_app
    return resolve_app()[0]
def profile(app):
    return {'app':str(app),'version':app.name,'dll_sha256':sha(app/'videoeditor.dll'),'adapter':1}
def native_status(app):
    record=ROOT/'state/native-capabilities.json'
    if not record.is_file():return 'unverified'
    data=read(record)
    adapter=Path(__file__).parent/'vendor/draft_crypto.py'
    if data.get('dll_sha256')==sha(app/'videoeditor.dll') and data.get('adapter_sha256')==sha(adapter):
        return data.get('read','unverified')
    return 'unverified'
def decode(raw,app):
    try:return json.loads(raw.decode('utf-8-sig'))
    except (UnicodeError,json.JSONDecodeError):
        from native_runtime import require
        require(app,'codec_roundtrip')
        if native_status(app)=='failed':raise ValueError('unsupported_codec: cached native decode failure for this DLL/adapter; source unchanged')
        from draft_ops import codec
        try:return codec(str(app))[0](raw)
        except Exception as e:raise ValueError('unsupported_codec: '+app.name+'; empty/failed native decode; original unchanged') from e
def load(source,app):
    return decode((Path(source)/'draft_content.json').read_bytes(),app)
def summary(c):
    return {'id':c.get('id'),'duration_us':c.get('duration'),'tracks':[
        {'id':t['id'],'type':t['type'],'segments':[{'id':s['id'],'material_id':s['material_id'],
         'target':s['target_timerange']} for s in t.get('segments',[])]} for t in c['tracks']]}
def integer(value):
    if type(value)!=int:raise ValueError('Timeline values must be integer microseconds')
    return value
def validate(c):
    ids=set();materials={m['id']:m for v in c['materials'].values() if isinstance(v,list) for m in v if isinstance(m,dict) and 'id' in m}
    duration=0
    for t in c['tracks']:
        if t['id'] in ids:raise ValueError('Duplicate track ID')
        ids.add(t['id']);previous=0
        for s in sorted(t['segments'],key=lambda s:s['target_timerange']['start']):
            if s['id'] in ids:raise ValueError('Duplicate segment ID')
            ids.add(s['id']);r=s['target_timerange'];a=integer(r['start']);d=integer(r['duration'])
            if a<previous or d<=0:raise ValueError('Overlapping/invalid segment: '+s['id'])
            previous=a+d;duration=max(duration,previous)
            if s['material_id'] not in materials:raise ValueError('Missing material reference')
            m=materials[s['material_id']]
            if m.get('path') and not Path(m['path']).is_file():raise ValueError('Missing local media')
            source=s.get('source_timerange')
            if source and m.get('type') not in ('photo','image'):
                if source['start']<0 or source['duration']<=0 or source['start']+source['duration']>m.get('duration',2**63):
                    raise ValueError('Source range exceeds material')
    if c['duration']!=duration:raise ValueError('Timeline duration mismatch')
    return {'file_validation':'passed','tracks':len(c['tracks']),'segments':len(ids)-len(c['tracks']),'duration_us':duration}
def build(plan,base):
    if plan.get('schema_version')!=2:raise ValueError('Expected schema_version 2')
    sys.path.insert(0,str(Path(__file__).parent/'vendor'))
    import pyJianYingDraft as d
    p=plan.get('project',{});script=d.ScriptFile(int(p.get('width',1920)),int(p.get('height',1080)),int(p.get('fps',30)),False)
    requested={}
    for t in plan['tracks']:
        kind=t['type']
        if kind not in ('video','audio','text'):raise ValueError('Unsupported track type')
        script.append_track(d.TrackSpec(getattr(d.TrackType,kind), name=t['id']))
        requested[t['id']]=t['id']
        for row in t['segments']:
            start=integer(row['start_us']);duration=integer(row['duration_us'])
            tr=d.Timerange(start,duration)
            if kind=='text':
                obj=d.TextSegment(row['text'],tr,style=d.TextStyle(**row.get('style',{})),clip_settings=d.ClipSettings(**row.get('clip_settings',{})),border=d.TextBorder(**row['border']) if row.get('border') else None)
            else:
                path=(base/row['path']).resolve()
                if not path.is_file():raise ValueError('Missing media: '+str(path))
                src=d.Timerange(integer(row.get('source_start_us',0)),duration)
                ctor=d.VideoSegment if kind=='video' else d.AudioSegment
                obj=ctor(str(path),tr,source_timerange=src,volume=float(row.get('volume',1)))
            obj.segment_id=row['id'];script.add_segment(obj,t['id'])
    c=json.loads(script.dumps())
    for track in c['tracks']:
        track['id']=requested[track['name']]
    # Normalize upstream's absent animation placeholder only in builder-owned text.
    material_ids={m['id'] for bucket in c['materials'].values() if isinstance(bucket,list) for m in bucket if isinstance(m,dict) and 'id' in m}
    for track in c['tracks']:
        if track['type']=='text':
            for seg in track['segments']:
                seg['extra_material_refs']=[r for r in seg.get('extra_material_refs',[]) if r in material_ids]
    validate(c);return c
def dependencies(c,s):
    if s.get('common_keyframes') or s.get('keyframe_refs'):return True
    safe={'speeds','canvases','sound_channel_mappings','material_colors','vocal_separations','texts'}
    kinds={m['id']:k for k,v in c['materials'].items() if isinstance(v,list) for m in v if isinstance(m,dict) and 'id' in m}
    return any(kinds.get(r) not in safe for r in s.get('extra_material_refs',[]))
def edit(c,plan,base):
    out=copy.deepcopy(c)
    for op in plan.get('operations',[]):
        tracks=[t for t in out['tracks'] if t['id']==op['track_id']]
        if op['op']=='add_track':
            if tracks:raise ValueError('Track already exists')
            generated=build({'schema_version':2,'tracks':[op['track']]},base)
            out['tracks']+=generated['tracks']
            for k,v in generated['materials'].items():out['materials'].setdefault(k,[]).extend(v)
            continue
        if len(tracks)!=1:raise ValueError('Expected unique track_id')
        track=tracks[0]
        if op['op']=='add':
            generated=build({'schema_version':2,'tracks':[{'id':track['id'],'type':track['type'],'segments':[op['segment']]}]},base)
            track['segments']+=generated['tracks'][0]['segments']
            for k,v in generated['materials'].items():out['materials'].setdefault(k,[]).extend(v)
            continue
        matches=[s for s in track['segments'] if s['id']==op['segment_id']]
        if len(matches)!=1:raise ValueError('Expected unique segment_id')
        seg=matches[0]
        if dependencies(out,seg):raise ValueError('unsupported_dependency: '+seg['id'])
        if op['op']=='remove':track['segments'].remove(seg)
        elif op['op']=='update':
            patch=op['changes']
            if set(patch)-{'start_us','duration_us','source_start_us','volume','text','style','path'}:raise ValueError('Unsupported edit field')
            for src,dest in [('start_us','start'),('duration_us','duration')]:
                if src in patch:seg['target_timerange'][dest]=integer(patch[src])
            if seg.get('source_timerange'):
                if 'source_start_us' in patch:seg['source_timerange']['start']=integer(patch['source_start_us'])
                if 'duration_us' in patch:seg['source_timerange']['duration']=integer(patch['duration_us'])
            if 'volume' in patch:seg['volume']=float(patch['volume'])
            for category in out['materials'].values():
                if not isinstance(category,list):continue
                for material in list(category):
                    if material.get('id')!=seg['material_id']:continue
                    # Clone shared material to limit updates to the selected segment.
                    m=copy.deepcopy(material);m['id']=uuid.uuid4().hex
                    if 'path' in patch:raise ValueError('Use remove + add to replace media and refresh metadata')
                    if 'text' in patch or 'style' in patch:
                        if track['type']!='text':raise ValueError('Text edit requires text track')
                        content=json.loads(m['content']);text=patch.get('text',content['text'])
                        content['text']=text
                        for st in content.get('styles',[]):
                            st['range']=[0,len(text)]
                            for k,v in patch.get('style',{}).items():
                                if k not in ('size','bold','italic'):raise ValueError('Unsupported existing text style')
                                st[k]=v
                        m['content']=json.dumps(content,ensure_ascii=False)
                    category.append(m);seg['material_id']=m['id'];break
        else:raise ValueError('Unknown operation')
    for t in out['tracks']:t['segments'].sort(key=lambda s:s['target_timerange']['start'])
    out['duration']=max((s['target_timerange']['start']+s['target_timerange']['duration'] for t in out['tracks'] for s in t['segments']),default=0)
    validate(out);return out
def stage(content,output,destination,source=None,app=None):
    output=Path(output).resolve();destination=Path(destination).resolve()
    if output.exists() or destination.exists():raise ValueError('Use new staging and destination directories')
    if source and (output==source or source in output.parents or destination==source or source in destination.parents):raise ValueError('Source/output overlap')
    if source:
        before={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
        original=(source/'draft_content.json').read_bytes()
        meta_raw=(source/'draft_meta_info.json').read_bytes();meta=decode(meta_raw,app)
        shutil.copytree(source,output)
        if before!={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}:raise ValueError('Source changed during snapshot')
    else:
        output.mkdir(parents=True)
        template=Path(__file__).parent/'vendor/pyJianYingDraft/assets/draft_meta_info.json'
        meta=read(template);original=b'{}';meta_raw=b'{}'
    meta.update(draft_id=str(uuid.uuid4()).upper(),draft_name=destination.name,draft_fold_path=str(destination).replace('\\','/'),tm_duration=content['duration'])
    from draft_ops import codec
    encoder=codec(str(app))[1]
    data=encoder(content,original);mdata=encoder(meta,meta_raw)
    (output/'draft_content.json').write_bytes(data);(output/'draft_meta_info.json').write_bytes(mdata)
    if source:
        nested=output/'Timelines'/content['id']
        if nested.is_dir():(nested/'draft_content.json').write_bytes(data)
    # Preserve original timeline IDs and layouts on copies. Minimal new projects use legacy-compatible root format.
    write(output/'batch-receipt.json',{'destination':str(destination),'project_id':meta['draft_id'],'file_validation':validate(content),
       'source_hashes':before if source else {},'registered':False,'in_app_validation':'not_performed'})
def running():
    if sys.platform!='win32':return False
    import subprocess
    return 'JianyingPro.exe' in subprocess.check_output(['tasklist','/FI','IMAGENAME eq JianyingPro.exe'],text=True)
def install(stage_path,projects,app=None):
    if running():raise ValueError('Save work and exit Jianying before installing a new draft')
    stage_path=Path(stage_path).resolve();projects=Path(projects).resolve()
    receipt=read(stage_path/'batch-receipt.json')
    if receipt.get('backend')=='bundled_lyra' and receipt.get('state')!='validated':
        raise ValueError('Native staging is incomplete; no registration performed')
    dest=Path(receipt['destination']).resolve()
    if dest.parent!=projects:raise ValueError('Destination must be a direct child of projects root')
    index=projects/'root_meta_info.json';original=index.read_bytes();value=json.loads(original.decode('utf-8-sig'))
    if dest.exists():raise ValueError('Destination already exists; not registered twice')
    app=app or app_dir()
    if receipt.get('backend')=='bundled_lyra':
        from native_bridge import validate as native_validate
        native_validate(stage_path,app)
    else:
        c=load(stage_path,app);validate(c)
    meta=decode((stage_path/'draft_meta_info.json').read_bytes(),app)
    entry=copy.deepcopy(value['all_draft_store'][0]) if value['all_draft_store'] else {}
    entry.update(meta);entry['draft_fold_path']=str(dest).replace('\\','/');entry['draft_json_file']=str(dest/'draft_content.json').replace('\\','/')
    ledger=stage_path.parent/(stage_path.name+'.transaction.json')
    write(ledger,{'state':'prepared','destination':str(dest),'index_sha256':sha(index)})
    shutil.copytree(stage_path,dest)
    if index.read_bytes()!=original:
        expected={str(p.relative_to(stage_path)):sha(p) for p in stage_path.rglob('*') if p.is_file()}
        actual={str(p.relative_to(dest)):sha(p) for p in dest.rglob('*') if p.is_file()}
        if expected==actual and dest.parent==projects:
            shutil.rmtree(dest)
            write(ledger,{'state':'rolled_back_index_conflict','destination':str(dest)})
        else:
            write(ledger,{'state':'directory_changed_needs_review','destination':str(dest)})
        raise ValueError('Index changed; new directory retained unregistered, no index overwritten')
    value['all_draft_store'].append(entry)
    backup=stage_path.parent/(stage_path.name+'.root-meta.backup.json');backup.write_bytes(original)
    write(index,value)
    write(ledger,{'state':'registered','destination':str(dest),'index_sha256':sha(index)})
    return {'registered':True,'destination':str(dest),'in_app_validation':'not_performed'}
def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['doctor','inventory','probe','list','inspect','create','edit','validate','install-copy'])
    p.add_argument('source',nargs='?');p.add_argument('--app');p.add_argument('--projects');p.add_argument('--plan');p.add_argument('--output');p.add_argument('--destination');p.add_argument('--details',action='store_true')
    p.add_argument('--required',nargs='+');p.add_argument('--adapter')
    a=p.parse_args()
    import native_runtime as runtime
    from native_bridge import inspect as native_inspect,validate as native_validate,edit_copy,normalize_created
    projects=Path(a.projects) if a.projects else runtime.projects_root()
    if a.command=='doctor':
        result=runtime.doctor_report(a.app,a.required)
    elif a.command=='inventory':
        selected,reason=runtime.resolve_app(a.app)
        result=dict(runtime.inventory(selected),selected_by=reason)
    elif a.command=='probe':
        if not a.output:p.error('probe requires --output NEW_PRIVATE_DIRECTORY')
        from native_probe import probe
        result=probe(a.output,a.app,a.adapter,a.required)
    elif a.command=='list':
        result={'projects':[{'directory':str(d),'content_sha256':sha(d/'draft_content.json')}for d in projects.iterdir()if d.is_dir()and(d/'draft_content.json').is_file()]}
    else:
        app=runtime.resolve_app(a.app)[0]
        runtime.require(app,'read')
        if a.command=='install-copy':
            result=install(a.source,projects,app)
        elif a.command in ('inspect','validate'):
            result=native_validate(a.source,app)if a.command=='validate'else native_inspect(a.source,app,'full'if a.details else'summary')
        else:
            if not all((a.plan,a.output,a.destination)):p.error('plan/output/destination required')
            plan=read(a.plan);source=Path(a.source).resolve()if a.command=='edit'else None
            if source:
                result=edit_copy(source,plan,a.output,a.destination,app)
            else:
                runtime.require(app,'create')
                c=build(plan,Path(a.plan).resolve().parent)
                stage(c,a.output,a.destination,app=app)
                result=read(Path(a.output)/'batch-receipt.json')
                result.update(backend='bundled_lyra',state='prepared')
                write(Path(a.output)/'batch-receipt.json',result)
                project=plan.get('project',{})
                result['native_validation']=normalize_created(Path(a.output),app,int(project.get('width',1920)),int(project.get('height',1080)))
                result.update(state='validated')
                write(Path(a.output)/'batch-receipt.json',result)
    if not a.details and isinstance(result,dict)and'source_hashes'in result:
        result=dict(result);result['source_file_count']=len(result.pop('source_hashes'))
    print(json.dumps(result,ensure_ascii=True))
    if result.get('status')in['failed','needs_local_adapter','needs_probe','needs_native_review']:raise SystemExit(2)

if __name__=='__main__':main()
