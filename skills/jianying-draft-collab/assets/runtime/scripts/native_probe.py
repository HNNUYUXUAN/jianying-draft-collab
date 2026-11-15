"""Bounded native acceptance using only generated media and external projects."""
import copy
import json
import math
from pathlib import Path
import shutil
import struct
import time
import uuid
import wave
import xml.etree.ElementTree as ET
import zlib

import native_runtime as r


def _png(path, rgb):
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    header=struct.pack('>IIBBBBB',16,16,8,2,0,0,0)
    path.write_bytes(bytes([137,80,78,71,13,10,26,10])+chunk(b'IHDR',header)+
                     chunk(b'IDAT',zlib.compress((b'\x00'+bytes(rgb)*16)*16))+chunk(b'IEND',b''))


def _wav(path):
    with wave.open(str(path),'wb')as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(48000)
        stream.writeframes(b''.join(struct.pack('<h',int(1500*math.sin(2*math.pi*330*i/48000)))for i in range(96000)))


def _nodes(result):
    nodes=result.get('json_result')
    if isinstance(nodes,str):nodes=json.loads(nodes)
    if not isinstance(nodes,list)or not all(isinstance(n,dict)and 'id'in n and 'type'in n for n in nodes):
        raise ValueError('Adapter must normalize extract to the stdraft json_result node list')
    return nodes


def probe(output,app=None,descriptor_path=None,required=None):
    import native_bridge as n
    output=Path(output).resolve();chosen,selected=r.resolve_app(app);identity=r.inventory(chosen)
    descriptor=r.descriptor_for(identity,descriptor_path)
    if output.exists():raise ValueError('Native probe requires a new output directory')
    for forbidden in [chosen.resolve(),r.projects_root().resolve()]:
        if output==forbidden or output.is_relative_to(forbidden):raise ValueError('Native probe output must stay outside the app and registered projects')
    output.mkdir(parents=True)
    index=r.projects_root()/'root_meta_info.json'
    index_before=r.digest(index)if index.is_file()else None
    started=time.monotonic();caps={};events=[]
    report={'status':'failed','identity':identity,'selected_by':selected,'adapter':descriptor,
            'protocol':r.PROTOCOL,'capabilities':caps,'events':events,'registered':False,
            'desktop_actions':0,'source_user_drafts_read':False,'output':str(output)}
    required=list(required or [*r.BASIC_CAPABILITIES,'independent_copy'])
    def index_stable():
        return (r.digest(index)if index.is_file()else None)==index_before
    def execute(args):
        if time.monotonic()-started>1800:raise TimeoutError('Native probe exceeded its 30 minute convergence budget')
        if not index_stable():raise ValueError('Project index changed during probe; no cache will be accepted')
        result=n.decode_response(n.transport(chosen,args,descriptor,cwd=output,timeout=60))
        events.append({'command':args[:3],'success':True})
        if not index_stable():raise ValueError('Project index changed during probe; no cache will be accepted')
        return result
    def extract(project):return _nodes(execute(['draft','extract','--ref',n.ref(project),'--scope','full']))
    def find(nodes,kind):return next(item for item in nodes if item['type']==kind)
    def mark(name,action):
        action();caps[name]='passed';r.write(output/'probe-progress.json',report)
    try:
        # Human-readable help is evidence, not an executable plan. The built-in
        # adapter is used only when its installed CLI exposes the required flags.
        for topic in [('project','create'),('extract',),('video','add'),('audio','add'),('text','add')]:
            raw=n.transport(chosen,['draft',*topic,'--help'],descriptor,cwd=output,timeout=15)
            text=raw.get('help_text','')if isinstance(raw,dict)else raw.stdout.decode('utf-8',errors='replace')
            if not text:raise ValueError('Installed native help unavailable; author a reviewed local adapter')
            (output/('help-'+'-'.join(topic)+'.txt')).write_text(text,encoding='utf-8')
            if descriptor['kind']=='bundled_lyra'and not all(token in text for token in (['--ref','--dir']if topic==('project','create')else['--ref'])):
                raise ValueError('Installed CLI flags differ; follow the local compatibility analysis')
        image=output/'calibration.png';replacement=output/'replacement.png';audio=output/'calibration.wav'
        _png(image,(25,80,120));_png(replacement,(80,120,25));_wav(audio)
        fixture=output/('native-acceptance-'+uuid.uuid4().hex[:10])
        mark('create',lambda:execute(['draft','project','create','--ref','local://'+fixture.name,'--dir',str(output)]))
        assert fixture.is_dir(),'Native engine did not create the external fixture'
        # A new empty CLI project has a 0x0 canvas. Establish the fixture canvas
        # before taking its baseline; blueprint sync otherwise initializes it.
        execute(['draft','config','--ref',n.ref(fixture),'--ratio','16:9'])
        mark('add_video',lambda:execute(['draft','video','add','--ref',n.ref(fixture),'--resource',n.ref(image),'--is-photo','true','--duration','2s','--track','0']))
        mark('add_audio',lambda:execute(['draft','audio','add','--ref',n.ref(fixture),'--resource',n.ref(audio),'--start','0s','--duration','2s','--track','1']))
        execute(['draft','audio','add','--ref',n.ref(fixture),'--resource',n.ref(audio),'--start','0s','--duration','2s','--track','2'])
        mark('add_text',lambda:execute(['draft','text','add','--ref',n.ref(fixture),'--content','Native acceptance','--start','0s','--duration','1s','--track','3']))
        original=extract(fixture);caps['read']='passed'
        assert sum(x['type']=='track'for x in original)==4,'Fixture must contain four tracks'
        assert {kind:sum(x['type']==kind for x in original)for kind in ['video','audio','text']}=={'video':1,'audio':2,'text':1}
        source_fixture=fixture
        (source_fixture/'opaque-probe-resource.bin').write_bytes(b'preserved opaque resource')
        source_hashes=n.hashes(source_fixture)
        clone=output/('native-copy-'+uuid.uuid4().hex[:10])
        execute(['draft','project','create','--ref','local://'+clone.name,'--dir',str(output)])
        assert r.read(clone/'draft_meta_info.json')['draft_id']!=r.read(source_fixture/'draft_meta_info.json')['draft_id']
        for source in source_fixture.iterdir():
            if source.name=='draft_meta_info.json':continue
            target=clone/source.name
            if source.is_dir():shutil.copytree(source,target,dirs_exist_ok=True)
            else:shutil.copy2(source,target)
        assert extract(clone)==original,'Copied native timeline changed before edits'
        fixture=clone
        report['source_fixture']=str(source_fixture)
        text_id=find(original,'text')['id'];video_id=find(original,'video')['id'];audio_id=find(original,'audio')['id']
        def check_action(cap,args,kind,check):
            if cap not in required:return
            execute([*args,'--ref',n.ref(fixture)])
            nodes=extract(fixture);assert check(next(x for x in nodes if x['id']==kind)),cap+' readback mismatch'
            caps[cap]='passed'
        check_action('text_content',['draft','text','content','--seg-id',text_id,'--content','Native roundtrip'],text_id,
                     lambda x:'Native roundtrip'in json.dumps(x,ensure_ascii=False))
        check_action('text_style',['draft','text','style','--seg-id',text_id,'--bold','true'],text_id,
                     lambda x:any(style.get('bold')is True for style in json.loads(x['attributes']['content'])['styles']))
        check_action('audio_volume',['draft','audio','volume','--seg-id',audio_id,'--linear','0.25'],audio_id,
                     lambda x:abs(x['attributes']['volume']-.25)<1e-6)
        check_action('video_volume',['draft','video','volume','--seg-id',video_id,'--linear','0'],video_id,
                     lambda x:x['attributes']['volume']==0)
        check_action('segment_move',['draft','segment','move','--seg-id',text_id,'--start','200ms'],text_id,
                     lambda x:x['timeline']['start.ms']==200)
        check_action('time_range',['draft','segment','time-range','--seg-id',text_id,'--duration','800ms'],text_id,
                     lambda x:x['timeline']['duration.ms']==800)
        if 'blueprint' in required:
            # Test media relinking through the engine's reverse-synced blueprint.
            before=extract(fixture);workspace=output/'blueprint'
            execute(['draft','blueprint','init','--workspace',str(workspace)])
            execute(['draft','blueprint','sync','--workspace',str(workspace),'--ref',n.ref(fixture),'--include-tracks'])
            resources=r.read(workspace/'resource_map.json');idmap={x['seg_id']:x['xml_id']for x in r.read(workspace/'id_map.json')}
            tree=ET.parse(workspace/'target_draft.xml');el=next(x for x in tree.getroot().iter()if x.attrib.get('id')==idmap[video_id])
            asset=copy.deepcopy(next(x for x in resources if x['asset_id']==el.attrib['ref']))
            asset.update(asset_id='probe_replacement',path=str(replacement),lyra_resource=n.ref(replacement));asset.pop('resource_id',None)
            resources.append(asset);el.set('ref',asset['asset_id'])
            tree.write(workspace/'target_draft.xml',encoding='unicode');r.write(workspace/'resource_map.json',resources)
            r.write(output/'blueprint-plan.json',execute(['draft','blueprint','plan','--workspace',str(workspace)]))
            execute(['draft','blueprint','apply','--workspace',str(workspace),'--ref',n.ref(fixture)])
            after=extract(fixture);old={x['id']:x for x in before};new={x['id']:x for x in after}
            assert old.keys()==new.keys(),'Blueprint relink changed node IDs'
            for key in old:
                a=copy.deepcopy(old[key]);bb=copy.deepcopy(new[key])
                if key==video_id:
                    assert Path(bb['attributes']['source']).resolve()==replacement.resolve()
                    a['attributes'].pop('source');bb['attributes'].pop('source')
                assert a==bb,'Blueprint relink changed unrelated fields'
            caps['blueprint']='passed'
        if 'segment_remove' in required:
            execute(['draft','segment','remove','--ref',n.ref(fixture),'--seg-id',text_id])
            assert not any(x['id']==text_id for x in extract(fixture));caps['segment_remove']='passed'
        # Fresh engine processes reopen each result above. This marker is only
        # asserted when the actual saved bytes are not already plaintext JSON.
        for content in [fixture/'draft_content.json',*fixture.glob('Timelines/*/draft_content.json')]:
            try:json.loads(content.read_text(encoding='utf-8-sig'))
            except (ValueError,UnicodeError):
                caps['encrypted_read']='passed';break
        assert index_stable(),'User project index changed'
        assert n.hashes(source_fixture)==source_hashes,'Source fixture changed while editing its copy'
        assert (fixture/'opaque-probe-resource.bin').read_bytes()==b'preserved opaque resource'
        caps['independent_copy']='passed'
        report['source_fixture_unchanged']=True
        missing=[key for key in required if caps.get(key)!='passed']
        if missing:raise ValueError('Required native capabilities were not proved: '+', '.join(missing))
        report.update(status='ready',evidence=str(output/'probe-report.json'),
                      adapter_sha256=r.adapter_hash(descriptor),project_index_unchanged=True,
                      elapsed_seconds=round(time.monotonic()-started,2),required=required,
                      in_app_validation='not_performed')
        r.write(output/'native-final.json',{'nodes':extract(fixture)})
        r.write(output/'probe-report.json',report)
        r.write(r.state_root()/identity['fingerprint']/'receipt.json',report)
        r.write(r.state_root()/'selection.json',{'app':str(chosen),'fingerprint':identity['fingerprint']})
        return report
    except Exception as error:
        report.update(status='needs_local_adapter',reason=str(error),error_type=type(error).__name__,
                      project_index_unchanged=index_stable(),elapsed_seconds=round(time.monotonic()-started,2),
                      actions=['Review this private help and progress evidence; analyze the selected installed version',
                               'At most three evidence-backed adapter candidates, one correction each, within 30 minutes',
                               'Do not change the application or start production until required capabilities pass'])
        r.write(output/'probe-report.json',report)
        return report
