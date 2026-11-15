"""Verified device-local draft bridge. No desktop automation."""
import hashlib,json,os,shutil,subprocess,tempfile,uuid,sys
from pathlib import Path
from pipeline import read,write,sha
import native_runtime as runtime
import native_verify as verification
ROOT=Path(__file__).resolve().parents[1]

def available(app,required=None):
    return runtime.doctor_report(app,required or ['read'])['status']=='ready'

def ref(path):return 'local://'+Path(path).resolve().as_posix()

def transport(app,args,descriptor,cwd=None,timeout=60):
    """Transport for reviewed isolated probes; production callers use run()."""
    app=Path(app).resolve()
    with tempfile.TemporaryDirectory(prefix='jy-native-') as td:
        request=Path(td)/'request.json'
        env={k:v for k,v in os.environ.items() if not any(t in k.upper() for t in ('API_KEY','APIKEY','SECRET','ACCESS_TOKEN'))}
        if descriptor['kind']=='local_python':
            module=Path(descriptor['module']).resolve()
            if not module.is_relative_to((runtime.state_root()/'local').resolve()):
                raise runtime.NativePreflightError('Local adapter module must stay in the reviewed device-local directory')
            write(request,{'module':str(module),'app':str(app),'args':args,'cwd':str(cwd or td),'timeout':timeout})
            result=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('native_local_worker.py')),str(request)],
                capture_output=True,timeout=timeout+10,env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if result.returncode:raise ValueError('Local native adapter worker failed; inspect private probe evidence')
            for line in reversed(result.stdout.decode('utf-8',errors='replace').splitlines()):
                try:
                    item=json.loads(line)
                    if isinstance(item,dict)and isinstance(item.get('native_local_result'),dict):return item['native_local_result']
                except ValueError:pass
            raise ValueError('Local native adapter returned no normalized result')
        write(request,{'executable':str(app/descriptor['cli']),'args':args,'cwd':str(cwd or td),'timeout_ms':timeout*1000})
        return subprocess.run([str(app/descriptor['host']),'--no-env-file',str(Path(__file__).with_name('native_cli.mjs')),str(request)],
           capture_output=True,timeout=timeout+10,env=env,
           creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)

def decode_response(result):
    if isinstance(result,dict):return result
    value=None
    for line in result.stdout.decode('utf8',errors='replace').splitlines():
        try:
            candidate=json.loads(line)
            if isinstance(candidate,dict) and 'err_code' in candidate:value=candidate
        except ValueError:pass
    if not value:raise ValueError('Native CLI returned no result envelope; exit='+str(result.returncode))
    if result.returncode or value['err_code']!=0:
        raise ValueError('Native CLI error '+str(value['err_code'])+': '+str(value.get('err_msg','')))
    return value.get('result') or {}

def run(app,args,cwd=None,timeout=60):
    receipt=runtime.require(app,runtime.capability_for(args))
    return decode_response(transport(app,args,receipt['adapter'],cwd,timeout))

def inspect(path,app,scope='summary'):
    result=run(app,['draft','extract','--ref',ref(path),'--scope',scope])
    nodes=result.get('json_result')
    if isinstance(nodes,str):nodes=json.loads(nodes)
    if not isinstance(nodes,list):raise ValueError('Unknown native extract schema')
    return {'backend':'bundled_lyra','protocol':'stdraft','scope':scope,'nodes':nodes}
def hashes(path):
    return {str(p.relative_to(path)):sha(p) for p in Path(path).rglob('*') if p.is_file()}
def validate(path,app):
    nodes=inspect(path,app,'full')['nodes']
    checks=verification.validate_nodes(nodes)
    receipt_path=Path(path)/'batch-receipt.json';receipt_status='not_supplied'
    if receipt_path.is_file():
        receipt=read(receipt_path)
        if receipt.get('backend')=='bundled_lyra'and receipt.get('state')=='validated':
            expected=receipt.get('verified_nodes_sha256')or receipt.get('native_validation',{}).get('nodes_sha256')
            if not expected:raise ValueError('native_verified_snapshot_missing: validate the intended edit before registration')
            if expected!=checks['nodes_sha256']:raise ValueError('native_verification_stale: draft changed after verification')
            receipt_status='passed'
    return {'backend':'bundled_lyra','native_read':'passed',**checks,'verification_receipt':receipt_status,
            'desktop_actions':0,'in_app_validation':'not_performed'}
def commands(plan,summary):
    nodes={n['id']:n for n in summary['nodes']}
    tracks={n['id']:n for n in summary['nodes'] if n['type']=='track'}
    belongs={sid:t['id'] for t in tracks.values() for sid in t.get('attributes',{}).get('segments',[])}
    result=[]
    for op in plan.get('operations',[]):
        if op.get('op') not in ('update','remove'):raise ValueError('Native operations currently support update/remove; use native_actions for typed additions')
        sid=op['segment_id'];node=nodes.get(sid)
        if not node or node['type'] in ('track','draft'):raise ValueError('Unknown segment_id')
        if op.get('track_id')!=belongs.get(sid):raise ValueError('Track/segment mismatch')
        if op['op']=='remove':
            result.append(['segment','remove','--seg-id',sid]);continue
        changes=op['changes'];kind=node['type']
        if set(changes)-{'text','start_us','duration_us','volume','style'}:raise ValueError('Unverified native update field')
        if 'text' in changes:
            if kind not in ('text','subtitle','lyrics'):raise ValueError('Expected text segment')
            result.append(['text','content','--seg-id',sid,'--content',changes['text']])
        if 'start_us' in changes:
            if type(changes['start_us'])!=int or changes['start_us']<0:raise ValueError('Invalid start_us')
            result.append(['segment','move','--seg-id',sid,'--start',str(changes['start_us'])+'us'])
        if 'duration_us' in changes:
            if type(changes['duration_us'])!=int or changes['duration_us']<=0:raise ValueError('Invalid duration_us')
            result.append(['segment','time-range','--seg-id',sid,'--duration',str(changes['duration_us'])+'us'])
        if 'volume' in changes:
            if kind not in ('audio','video'):raise ValueError('Expected audio/video segment')
            result.append([kind,'volume','--seg-id',sid,'--linear',str(changes['volume'])])
        if 'style' in changes:
            args=['text','style','--seg-id',sid]
            for k,v in changes['style'].items():
                if k not in ('size','bold','italic','color','alpha'):raise ValueError('Unverified native style property')
                args+=['--'+k,str(v).lower() if isinstance(v,bool) else str(v)]
            result.append(args)
    allowed={('segment','move'),('segment','time-range'),('segment','remove'),
      ('text','content'),('text','style'),('text','add'),('text','remove'),
      ('video','add'),('video','volume'),('audio','add'),('audio','volume')}
    for action in plan.get('native_actions',[]):
        if not isinstance(action,list) or len(action)<2 or tuple(action[:2]) not in allowed:
            raise ValueError('Unsupported native action')
        if not all(isinstance(x,str) for x in action) or any(x in ('--ref','--dir','--action') or x.startswith('--ref=') or x.startswith('--dir=') or x.startswith('--action=') for x in action):
            raise ValueError('Action may not override destination/reference')
        result.append(action)
    if not result:raise ValueError('Empty native edit plan')
    return result
def edit_copy(source,plan,output,destination,app):
    runtime.require(app,'independent_copy')
    source=Path(source).resolve();output=Path(output).resolve();destination=Path(destination).resolve()
    if output.exists() or destination.exists() or output==source or source in output.parents or source==destination or source in destination.parents:
        raise ValueError('Source/output overlap or existing output')
    before=hashes(source)
    project_index=runtime.projects_root()/'root_meta_info.json'
    index_hash=sha(project_index)if project_index.is_file()else None
    def index_stable():return (sha(project_index)if project_index.is_file()else None)==index_hash
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jy-snapshot-',dir=output.parent) as td:
        snapshot=Path(td)/source.name;shutil.copytree(source,snapshot)
        if hashes(source)!=before:raise ValueError('Source changed while copying; no edit submitted')
        summary=inspect(snapshot,app)
        before_nodes=inspect(snapshot,app,'full')['nodes']
        edits=commands(plan,summary)
        output.parent.mkdir(parents=True,exist_ok=True)
        run(app,['draft','project','create','--ref','local://'+output.name,'--dir',str(output.parent)])
        if not output.is_dir():raise ValueError('CLI did not create the requested external directory')
        # Keep fresh project identity; copy the complete source timeline and opaque resources.
        for p in snapshot.iterdir():
            if p.name in ('draft_meta_info.json','batch-receipt.json'):continue
            target=output/p.name
            if p.is_dir():shutil.copytree(p,target,dirs_exist_ok=True)
            else:shutil.copy2(p,target)
        write(output/'batch-receipt.json',{'backend':'bundled_lyra','state':'prepared','source_hashes':before,'destination':str(destination),'project_index_sha256':index_hash})
        # Typed content commands are not accepted by the CLI's action-chain parser.
        # Execute the prevalidated plan sequentially on this isolated staging copy.
        for index,action in enumerate(edits):
            if not index_stable():raise ValueError('Project index changed; prepared copy retained')
            run(app,['draft',*action,'--ref',ref(output)])
            write(output/'native-progress.json',{'completed':index+1,'total':len(edits)})
        after=inspect(output,app,'full')
        proof=verification.verify_intent(before_nodes,after['nodes'],edits,plan)
        try:verification.validate_nodes(after['nodes'])
        except ValueError as error:proof['issues'].append({'code':'invalid_native_readback','reason':str(error)})
        source_stable=hashes(source)==before
        if not source_stable:proof['issues'].append({'code':'source_changed_concurrently'})
        if not index_stable():proof['issues'].append({'code':'project_index_changed_concurrently'})
        proof['passed']=not proof['issues']
        if not proof['passed']:
            receipt={'backend':'bundled_lyra','state':'needs_native_review','status':'needs_native_review',
              'source_hashes':before,'source_unchanged':source_stable,'destination':str(destination),
              'registered':False,'edit_verification':proof,'native_actions':len(edits),
              'project_index_unchanged':index_stable(),'desktop_actions':0,'in_app_validation':'not_performed'}
            write(output/'batch-receipt.json',receipt)
            return receipt
        native_changes=proof['changes']
        meta=read(output/'draft_meta_info.json')
        meta.update(draft_name=destination.name,draft_fold_path=destination.as_posix())
        summary_after=inspect(output,app)
        meta['tm_duration']=round(max((n.get('timeline',{}).get('end.ms',0) for n in summary_after['nodes']),default=0)*1000)
        write(output/'draft_meta_info.json',meta)
        native_validation=validate(output,app)
        if native_validation['nodes_sha256']!=proof['verified_nodes_sha256']:proof['issues'].append({'code':'native_changed_during_validation'})
        if hashes(source)!=before:proof['issues'].append({'code':'source_changed_concurrently'})
        if not index_stable():proof['issues'].append({'code':'project_index_changed_concurrently'})
        proof['passed']=not proof['issues']
        receipt={'backend':'bundled_lyra','state':'validated','source_hashes':before,'source_unchanged':True,
          'destination':str(destination),'project_id':meta['draft_id'],'registered':False,
          'native_validation':native_validation,'edit_verification':proof,'verified_nodes_sha256':proof['verified_nodes_sha256'],
          'project_index_unchanged':index_stable(),'native_actions':len(edits),'native_changes':native_changes,'native_linked_changes':sum(c['native_linked_change'] for c in native_changes),'desktop_actions':0,'in_app_validation':'not_performed'}
        if not proof['passed']:receipt.update(state='needs_native_review',status='needs_native_review',source_unchanged=hashes(source)==before)
        write(output/'batch-receipt.json',receipt)
        return receipt
def normalize_created(output,app,width,height):
    # Ratio-config rewrites dimensions to 1080p. Preserve the requested canvas;
    # parse the generated draft through the native engine without that mutation.
    summary=inspect(output,app)
    draft=next(n for n in summary['nodes'] if n['type']=='draft')
    attrs=draft.get('attributes',{})
    if attrs.get('width')!=width or attrs.get('height')!=height:
        raise ValueError('Native canvas differs from requested dimensions')
    return validate(output,app)
