"""Readback checks for normalized stdraft nodes; no native execution."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re

TEXT_TYPES={'text','subtitle','lyrics'}
MEDIA_TYPES={'video','audio'}


def text_document(node):
    content=node.get('attributes',{}).get('content')
    try:document=json.loads(content)if isinstance(content,str)else content
    except (ValueError,TypeError):return None
    return document if isinstance(document,dict)and isinstance(document.get('text'),str)else None


def normalized(node):
    result=copy.deepcopy(node)
    if node.get('type')in TEXT_TYPES:
        document=text_document(node)
        if document is not None:result['attributes']['content']=document
    return result


def nodes_sha256(nodes):
    ordered=sorted((normalized(node)for node in nodes),key=lambda node:node['id'])
    return hashlib.sha256(json.dumps(ordered,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')).hexdigest()


def fields_changed(before,after,prefix=''):
    if before==after:return []
    if isinstance(before,dict)and isinstance(after,dict):
        result=[]
        for key in sorted(before.keys()|after.keys()):
            path=(prefix+'.'if prefix else'')+key
            if key not in before or key not in after:result.append(path)
            else:result.extend(fields_changed(before[key],after[key],path))
        return result
    if isinstance(before,list)and isinstance(after,list)and len(before)==len(after):
        return [field for index,(a,b)in enumerate(zip(before,after))for field in fields_changed(a,b,prefix+'.'+str(index))]
    return [prefix or'$node']


def local_path(source):
    if source.startswith('local://'):
        source=source[len('local://'):]
        if len(source)>2 and source[0]=='/'and source[2]==':':source=source[1:]
    return Path(source)


def validate_nodes(nodes):
    if not isinstance(nodes,list)or not nodes:raise ValueError('Native readback returned no nodes')
    ids=[node.get('id')for node in nodes]
    if any(not isinstance(sid,str)or not sid for sid in ids)or len(set(ids))!=len(ids):raise ValueError('Native node IDs must be present and unique')
    byid={node['id']:node for node in nodes}
    if sum(node.get('type')=='draft'for node in nodes)!=1:raise ValueError('Native readback must contain one draft root')
    media=0;segments=0;tracks=0;remote=[]
    for node in nodes:
        kind=node.get('type')
        if node.get('parent_id')and node['parent_id']not in byid:raise ValueError('Missing native parent: '+node['id'])
        if kind=='track':
            tracks+=1
            members=node.get('attributes',{}).get('segments',[])
            if not isinstance(members,list)or len(set(members))!=len(members)or any(sid not in byid for sid in members):raise ValueError('Invalid native track members: '+node['id'])
        elif kind!='draft':
            segments+=1
            if kind in MEDIA_TYPES|TEXT_TYPES:
                timing=node.get('timeline',{});values=[timing.get(name)for name in ['start.ms','duration.ms','end.ms']]
                if any(isinstance(value,bool)or not isinstance(value,(int,float))or not math.isfinite(value)for value in values):raise ValueError('Invalid native timeline numbers: '+node['id'])
                start,duration,end=values
                if start<0 or duration<=0 or abs(start+duration-end)>1:raise ValueError('Invalid native timeline interval: '+node['id'])
        if kind in MEDIA_TYPES:
            source=node.get('attributes',{}).get('source')
            if not isinstance(source,str)or not source:raise ValueError('Missing native media source: '+node['id'])
            if '://'in source and not source.startswith('local://'):remote.append(node['id'])
            elif not local_path(source).is_file():raise ValueError('Missing native local media: '+node['id'])
            else:media+=1
    return {'tracks':tracks,'segments':segments,'local_media_verified':media,'remote_media_unverified':remote,
            'nodes_sha256':nodes_sha256(nodes),'node_validation':'passed'}


def _flags(action):
    result={};index=2
    while index<len(action):
        token=action[index]
        if not token.startswith('--'):raise ValueError('Native action has an unpaired value')
        if '='in token:key,value=token.split('=',1);index+=1
        elif index+1<len(action)and not action[index+1].startswith('--'):key,value=token,action[index+1];index+=2
        else:key,value=token,'true';index+=1
        if key in result:raise ValueError('Repeated native option: '+key)
        result[key]=value
    return result


def _duration_us(value):
    match=re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(us|ms|s|min)',str(value))
    if not match:raise ValueError('Unverifiable native duration: '+str(value))
    return float(match[1])*{'us':1,'ms':1000,'s':1000000,'min':60000000}[match[2]]


def _number(value):
    number=float(value)
    if not math.isfinite(number):raise ValueError('Non-finite requested number')
    return number


def _bool(value):
    if str(value).lower()not in ['true','false']:raise ValueError('Native style boolean must be true/false')
    return str(value).lower()=='true'


def _color(value):
    text=str(value).removeprefix('#').removeprefix('0x')
    if not re.fullmatch(r'[0-9a-fA-F]{6}',text):raise ValueError('Native color must be #RRGGBB or 0xRRGGBB')
    return [int(text[index:index+2],16)/255 for index in [0,2,4]]


def _equal_number(actual,expected,tolerance=1e-6):
    return isinstance(actual,(int,float))and not isinstance(actual,bool)and math.isfinite(actual)and abs(actual-expected)<=tolerance


def verify_intent(before_nodes,after_nodes,actions,plan):
    """Check requested values and every changed field, including root/track nodes."""
    before={node['id']:normalized(node)for node in before_nodes};after={node['id']:normalized(node)for node in after_nodes}
    issues=[];requirements={};removed=set();additions=[];target_allowed={}
    def issue(code,sid,field=None):issues.append({'code':code,'segment_id':sid,**({'field':field}if field else{})})
    def allow(sid,*fields):target_allowed.setdefault(sid,set()).update(fields)
    try:
        for action in actions:
            group,operation=action[:2];flags=_flags(action)
            if operation=='add':
                supported={'--resource','--track','--start','--duration','--is-photo'}if group=='video'else {'--resource','--track','--start','--duration'}if group=='audio'else {'--content','--track','--start','--duration','--text-type'}
                if flags.keys()-supported:raise ValueError('Native addition needs explicit verification for these options: '+', '.join(flags.keys()-supported))
                additions.append((group,flags));continue
            ids=flags.get('--seg-id','').split(',')
            if not all(ids):raise ValueError('Native action needs explicit segment IDs')
            for sid in ids:
                expected=requirements.setdefault(sid,{})
                if operation=='remove':removed.add(sid);continue
                if operation=='content':
                    expected['text']=flags['--content'];allow(sid,'attributes.content.text')
                elif operation=='volume':
                    expected['volume']=_number(flags['--linear']);allow(sid,'attributes.volume')
                elif operation=='move':
                    expected['start_us']=_duration_us(flags['--start']);allow(sid,'timeline.start.ms','timeline.end.ms')
                elif operation=='time-range':
                    expected['duration_us']=_duration_us(flags['--duration']);allow(sid,'timeline.duration.ms','timeline.end.ms')
                elif operation=='style':
                    if flags.keys()-{'--seg-id','--bold','--italic','--size','--color','--alpha'}:raise ValueError('Native style contains an unverified option')
                    for key,parser in [('bold',_bool),('italic',_bool),('size',_number),('color',_color),('alpha',_number)]:
                        if '--'+key in flags:expected['style.'+key]=parser(flags['--'+key])
                else:raise ValueError('Unverifiable native operation')
    except (ValueError,KeyError)as error:
        return {'passed':False,'issues':[{'code':'unverifiable_plan','reason':str(error)}],'changes':[]}
    explicit={}
    for row in plan.get('allowed_linked_changes',[]):
        if not isinstance(row,dict)or not isinstance(row.get('segment_id'),str)or not isinstance(row.get('fields'),list)or not row['fields']or not row.get('reason'):
            issue('invalid_linked_allowance','');continue
        if any(not isinstance(field,str)or not field or'*'in field for field in row['fields']):
            issue('invalid_linked_allowance',row['segment_id']);continue
        explicit.setdefault(row['segment_id'],set()).update(row['fields'])
    for sid,expected in requirements.items():
        if sid not in before:issue('unknown_requested_node',sid);continue
        if sid in removed:
            if sid in after:issue('requested_removal_missing',sid)
            continue
        if sid not in after:issue('requested_node_missing',sid);continue
        node=after[sid];attrs=node.get('attributes',{});timing=node.get('timeline',{});document=text_document(node)
        styles=document.get('styles',[])if document else[]
        if 'text'in expected:
            if not document or document.get('text')!=expected['text']:issue('requested_value_mismatch',sid,'attributes.content.text')
            maximum=len(expected['text'].encode('utf-16-le'))//2
            for index,style in enumerate(styles):
                limits=style.get('range')
                if not isinstance(limits,list)or len(limits)!=2 or not 0<=limits[0]<=limits[1]<=maximum:issue('invalid_text_style_range',sid,'attributes.content.styles.'+str(index)+'.range')
                else:
                    allow(sid,'attributes.content.styles.'+str(index)+'.range')
                    allow(sid,*('attributes.content.styles.'+str(index)+'.range.'+str(i)for i in [0,1]))
        if 'volume'in expected and not _equal_number(attrs.get('volume'),expected['volume']):issue('requested_value_mismatch',sid,'attributes.volume')
        for key,field in [('start_us','start.ms'),('duration_us','duration.ms')]:
            if key in expected and not _equal_number(timing.get(field),expected[key]/1000,1):issue('requested_value_mismatch',sid,'timeline.'+field)
        if any(key.startswith('style.')for key in expected)and not styles:issue('missing_text_style_readback',sid)
        for key,value in expected.items():
            if not key.startswith('style.'):continue
            name=key[6:]
            if name=='size':
                allow(sid,'attributes.font_size')
                if not _equal_number(attrs.get('font_size'),value):issue('requested_value_mismatch',sid,'attributes.font_size')
            if name=='alpha':
                allow(sid,'attributes.text_alpha')
                if not _equal_number(attrs.get('text_alpha'),value):issue('requested_value_mismatch',sid,'attributes.text_alpha')
            if name=='color'and attrs.get('font_color'):
                encoded=str(attrs['font_color']).removeprefix('#').removeprefix('0x')
                if len(encoded)==8 and encoded[-2:].lower()=='ff':encoded=encoded[:6]
                try:matches=all(_equal_number(a,b)for a,b in zip(_color(encoded),value))
                except ValueError:matches=False
                if matches:allow(sid,'attributes.font_color')
                else:issue('requested_value_mismatch',sid,'attributes.font_color')
            for index,style in enumerate(styles):
                prefix='attributes.content.styles.'+str(index)
                if name in ['bold','italic']:
                    allow(sid,prefix+'.'+name)
                    if bool(style.get(name,False))!=value:issue('requested_value_mismatch',sid,prefix+'.'+name)
                elif name=='size':
                    allow(sid,prefix+'.size')
                    if not _equal_number(style.get('size'),value):issue('requested_value_mismatch',sid,prefix+'.size')
                elif name=='color':
                    color=style.get('fill',{}).get('content',{}).get('solid',{}).get('color')
                    allow(sid,*(prefix+'.fill.content.solid.color.'+str(i)for i in [0,1,2]))
                    if not isinstance(color,list)or len(color)!=3 or not all(_equal_number(a,b)for a,b in zip(color,value)):issue('requested_value_mismatch',sid,prefix+'.fill.content.solid.color')
                    if 'useLetterColor'in style:
                        allow(sid,prefix+'.useLetterColor')
                        if style['useLetterColor']is not True:issue('requested_value_mismatch',sid,prefix+'.useLetterColor')
                elif name=='alpha'and 'alpha'in style.get('fill',{}):
                    allow(sid,prefix+'.fill.alpha')
                    if not _equal_number(style['fill']['alpha'],value):issue('requested_value_mismatch',sid,prefix+'.fill.alpha')
    added=set(after)-set(before);matched=set();added_segments=set()
    for group,flags in additions:
        candidates=[]
        for sid in added-matched:
            node=after[sid]
            if node.get('type')!=group:continue
            doc=text_document(node);attrs=node.get('attributes',{});timing=node.get('timeline',{})
            if '--content'in flags and(not doc or doc.get('text')!=flags['--content']):continue
            if '--resource'in flags:
                expected_source=flags['--resource']
                if not expected_source.startswith('local://')or local_path(attrs.get('source','')).resolve()!=local_path(expected_source).resolve():continue
            if '--track'in flags:
                track=next((item for item in after.values()if item.get('type')=='track'and sid in item.get('attributes',{}).get('segments',[])),None)
                if not track or not _equal_number(track['attributes'].get('track_index'),_number(flags['--track'])):continue
            if '--is-photo'in flags and ((attrs.get('meta_type')in ['photo','image'])!=_bool(flags['--is-photo'])):continue
            if '--text-type'in flags and attrs.get('meta_type')!=flags['--text-type']:continue
            if any(key in flags and not _equal_number(timing.get(field),_duration_us(flags[key])/1000,1)for key,field in [('--start','start.ms'),('--duration','duration.ms')]):continue
            candidates.append(sid)
        if not candidates:issue('requested_addition_missing','',group);continue
        sid=sorted(candidates)[0];matched.add(sid);added_segments.add(sid)
    removed_tracks=set()
    for sid,node in before.items():
        if node.get('type')=='track'and sid not in after:
            members=node.get('attributes',{}).get('segments',[])
            if members and set(members)<=removed:removed_tracks.add(sid)
    old_order=sorted((node for node in before.values()if node.get('type')=='track'),key=lambda node:node.get('attributes',{}).get('track_index',0))
    for sid,node in after.items():
        if node.get('type')!='track':continue
        members=node.get('attributes',{}).get('segments',[])
        if sid in before:
            old_members=before[sid].get('attributes',{}).get('segments',[])
            retained=[item for item in old_members if item not in removed]
            actual_retained=[item for item in members if item not in added_segments]
            moved=any('start_us'in requirements.get(item,{})for item in retained)
            expected_retained=sorted(retained,key=lambda item:after[item].get('timeline',{}).get('start.ms',0))if moved else retained
            if actual_retained==expected_retained and set(members)==(set(old_members)-removed)|(set(members)&added_segments):
                allow(sid,'attributes.segments',*('attributes.segments.'+str(i)for i in range(max(len(members),len(old_members)))))
            old_index=before[sid].get('attributes',{}).get('track_index')
            expected_index=old_index-sum(item['id']in removed_tracks for item in old_order if item.get('attributes',{}).get('track_index',0)<old_index)
            if node.get('attributes',{}).get('track_index')==expected_index:allow(sid,'attributes.track_index')
        elif members and set(members)<=added_segments:
            matched.add(sid)
    changes=[]
    for sid in sorted(before.keys()|after.keys()):
        a=before.get(sid);bb=after.get(sid)
        fields=['$node']if a is None or bb is None else fields_changed(a,bb)
        if not fields:continue
        if a is None and sid in matched:unapproved=[]
        elif bb is None and sid in removed|removed_tracks:unapproved=[]
        else:unapproved=[field for field in fields if field not in target_allowed.get(sid,set())|explicit.get(sid,set())]
        for field in unapproved:issue('unrequested_native_change',sid,field)
        changes.append({'segment_id':sid,'fields':fields,'added':a is None,'removed':bb is None,
                        'explicit_target':sid in requirements,'native_linked_change':sid not in requirements,
                        'unapproved_fields':unapproved})
    return {'passed':not issues,'issues':issues,'changes':changes,'requested_nodes':sorted(requirements),
            'linked_allowances':plan.get('allowed_linked_changes',[]),'verified_nodes_sha256':nodes_sha256(after_nodes)}
