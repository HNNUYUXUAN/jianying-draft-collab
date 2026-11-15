"""Render an authored score or supplied music and protect the unchanged narration."""
from __future__ import annotations
from pathlib import Path
import json,math,os,re,shutil,subprocess,wave
import numpy as np
from pipeline import write,read,sha,fingerprint
from music_adapter import ROOT,MusicPlanRequired,source_spec,render_score,digest

RATE=48000
FILES=('dialogue.wav','bgm.wav','mix.wav')
MIX_DEFAULTS={'target_gap_db':26.,'minimum_gap_p10_db':24.,'observation_rms_dbfs':-30.,
 'speech_duck_db':14.,'gap_ms':1500.,'lookahead_ms':300.,'hold_ms':650.,
 'recovery_db_per_second':6.,'descent_db_per_second':37.5,
 'activity_dbfs':-42.,'speech_window_dbfs':-35.,'fade_in_ms':2000.,'fade_out_ms':5000.,
 'peak_ceiling_dbtp':-1.}
LEGACY_DEFAULTS={'voice_lufs':-16,'music_lufs':-22,'duck_db':8,'attack_ms':150,'release_ms':600,'gap_ms':800}

def _ffmpeg(root=ROOT,explicit=None):
    if explicit:return Path(explicit).resolve()
    config=Path(root)/'runtime-config.json'
    value=read(config).get('media',{}).get('ffmpeg','tools/ffmpeg/bin/ffmpeg.exe')if config.is_file()else'tools/ffmpeg/bin/ffmpeg.exe'
    path=Path(value)
    if not path.is_absolute():path=Path(root)/path
    path=path.resolve()
    if not path.is_file():raise RuntimeError('Dedicated FFmpeg is missing; repair the local runtime')
    return path
def _run(ff,args):
    done=subprocess.run([str(ff),'-hide_banner','-nostdin','-y',*map(str,args)],capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt'else 0)
    if done.returncode:raise RuntimeError('FFmpeg music operation failed: '+done.stderr.decode('utf-8',errors='replace')[-1400:])
    return done
def _decode(ff,path):
    done=_run(ff,['-v','error','-i',path,'-f','f32le','-ar',str(RATE),'-ac','2','-'])
    return np.frombuffer(done.stdout,np.float32).reshape(-1,2).copy()
def _write_pcm(path,data):
    with wave.open(str(path),'wb')as stream:
        stream.setnchannels(2);stream.setsampwidth(2);stream.setframerate(RATE)
        for start in range(0,len(data),RATE*10):
            stream.writeframes(np.clip(np.round(data[start:start+RATE*10]*32768),-32768,32767).astype('<i2').tobytes())
def _rms(data,window):
    count=len(data)//window
    if not count:return np.empty(0)
    squared=np.square(data[:count*window].reshape(count,window,2),dtype=np.float64)
    return 10*np.log10(np.mean(squared,axis=(1,2))+1e-20)
def measure(ff,path):
    done=_run(ff,['-i',path,'-af','loudnorm=print_format=json','-f','null','-'])
    log=done.stderr.decode('utf-8',errors='replace');start=log.rfind('{')
    if start<0:raise RuntimeError('No loudness measurement was returned')
    return json.JSONDecoder().raw_decode(log[start:])[0]

def envelope(n,intervals,rate=RATE,duck_db=8,attack_ms=150,release_ms=600,gap_ms=800):
    """Historical envelope helper, retained for valid legacy-cache verification."""
    merged=[]
    for a,b in sorted(intervals):
        if merged and a-merged[-1][1]<gap_ms/1000:merged[-1][1]=max(b,merged[-1][1])
        else:merged.append([a,b])
    result=np.ones(n,dtype=np.float32);low=10**(-duck_db/20)
    for a,b in merged:
        start=max(0,min(n,round(a*rate)));end=max(start,min(n,round(b*rate)))
        pre=max(0,start-round(attack_ms/1000*rate));post=min(n,end+round(release_ms/1000*rate))
        if start>pre:result[pre:start]=np.minimum(result[pre:start],np.linspace(1,low,start-pre))
        result[start:end]=np.minimum(result[start:end],low)
        if post>end:result[end:post]=np.minimum(result[end:post],np.linspace(low,1,post-end))
    return result

def speech_intervals(voice,cues,rate=RATE):
    """Historical cue/PCM intersection, retained for callers reading old receipts."""
    n=len(voice);step=round(.02*rate);coverage=np.zeros(n,dtype=bool)
    for cue in cues:coverage[max(0,round(cue['start_ms']*rate/1000)):min(n,round(cue['end_ms']*rate/1000))]=True
    active=[]
    for a in range(0,n,step):
        b=min(n,a+step)
        if coverage[a:b].any()and np.sqrt(np.mean(voice[a:b]**2))>10**(-35/20):
            if active and abs(active[-1][1]-a/rate)<1e-8:active[-1][1]=b/rate
            else:active.append([a/rate,b/rate])
    return active

def legacy_cache(dialogue,cues,out,options=None,*,root=ROOT):
    """Recognize the old input fingerprint; never synthesize a replacement drum bed."""
    options=options or {};out=Path(out);receipt=out/'music-receipt.json'
    if set(options)-set(LEGACY_DEFAULTS)or not receipt.is_file():return None
    old=read(receipt)
    if old.get('version',1)!=1 or old.get('recipe',{}).get('source')!='vendor/music_synth.py; MUSIC_LICENSE':return None
    lock=read(Path(root)/'music-toolchain.json')['legacy_cache']
    opts={**LEGACY_DEFAULTS,**options}
    expected=fingerprint({'version':1,'implementation':lock['implementation_sha256'],'synth':lock['synth_sha256'],
        'dialogue':sha(dialogue),'cues':cues,'recipe':lock['recipe'],'options':opts})
    if old.get('identity')!=expected or any(not(out/name).is_file()for name in FILES):return None
    try:
        with wave.open(str(dialogue))as source:n=source.getnframes();rate=source.getframerate()
        for name in FILES:
            with wave.open(str(out/name))as stream:
                if stream.getnframes()!=n or stream.getframerate()!=rate:return None
        if float(old['mix_measurement']['input_tp'])>-1:return None
    except (KeyError,ValueError,wave.Error):return None
    return {**old,'cache_compatibility':'verified legacy input fingerprint; original outputs retained'}

def request_identity(spec=None,*,base_dir=None,root=ROOT):
    """A saved/native project may resume this request, but a changed one needs a new version."""
    value=source_spec(spec,base_dir)
    content={}
    for key in ('score','file'):
        if value.get(key)and Path(value[key]).is_file():content[key]=sha(value[key])
    config=Path(root)/'runtime-config.json';runtime_fingerprint={'configuration':sha(config)if config.is_file()else None}
    try:runtime_fingerprint['ffmpeg']=digest(_ffmpeg(root))
    except RuntimeError:runtime_fingerprint['ffmpeg']=None  # preflight reports the missing capability
    if config.is_file():
        music_config=read(config).get('music',{}).get('config')
        if music_config:
            f=Path(music_config)
            if not f.is_absolute():f=Path(root)/f
            runtime_fingerprint['music_config']=digest(f)if f.is_file()else None
    return fingerprint({'spec':value,'source_hashes':content,'implementation':sha(__file__),
        'adapter':sha(Path(__file__).with_name('music_adapter.py')),'toolchain':sha(Path(root)/'music-toolchain.json'),'runtime':runtime_fingerprint})

def mix_arrays(voice,music,cues,options=None):
    """Sample-aligned narration ducking; pure numeric routine used by regression tests."""
    opts={**MIX_DEFAULTS,**(options or {})}
    unknown=set(opts)-set(MIX_DEFAULTS)
    if unknown:raise ValueError('Unknown music.mix fields: '+', '.join(sorted(unknown)))
    if any(type(v)not in (int,float)or not math.isfinite(v)for v in opts.values()):raise ValueError('Music mixing values must be finite numbers')
    for key in ('target_gap_db','minimum_gap_p10_db','speech_duck_db','gap_ms','lookahead_ms','hold_ms','recovery_db_per_second','descent_db_per_second','fade_in_ms','fade_out_ms'):
        if opts[key]<0:raise ValueError('Music mixing durations and reductions cannot be negative')
    if opts['target_gap_db']<opts['minimum_gap_p10_db']:raise ValueError('Target gap must cover the required P10 gap')
    if not(-60<=opts['observation_rms_dbfs']<=-12):raise ValueError('Observation music reference must be between -60 and -12 dBFS RMS')
    if opts['peak_ceiling_dbtp']>-1:raise ValueError('Mix true-peak ceiling cannot exceed -1 dBTP')
    voice=np.asarray(voice,dtype=np.float32);music=np.asarray(music,dtype=np.float32)
    if voice.shape!=music.shape or voice.ndim!=2 or voice.shape[1]!=2 or not len(voice):raise ValueError('Voice and music need matching, nonempty stereo sample arrays')
    if not np.isfinite(voice).all()or not np.isfinite(music).all():raise ValueError('Audio contains non-finite samples')
    n=len(voice);step=RATE//50;count=(n+step-1)//step;times=(np.arange(count)+.5)/50
    vr=_rms(voice,RATE//2);mr=_rms(music,RATE//2);active=vr>opts['speech_window_dbfs']
    meaningful=mr[mr>-70];base=opts['observation_rms_dbfs']-float(np.median(meaningful))if len(meaningful)else 0.
    spans=[]
    for cue in cues:
        a=float(cue['start_ms'])/1000;b=float(cue['end_ms'])/1000
        if not math.isfinite(a+b)or b<a:raise ValueError('Invalid narration cue interval')
        spans.append([max(0,a-opts['lookahead_ms']/1000),min(n/RATE,b+opts['hold_ms']/1000)])
    v20=_rms(voice,step)
    for i in np.flatnonzero(v20>opts['activity_dbfs']):spans.append([max(0,i/50-opts['lookahead_ms']/1000),min(n/RATE,(i+1)/50+opts['hold_ms']/1000)])
    merged=[]
    for a,b in sorted(spans):
        if merged and a-merged[-1][1]<opts['gap_ms']/1000:merged[-1][1]=max(merged[-1][1],b)
        else:merged.append([a,b])
    speech=np.zeros(count,dtype=bool)
    for a,b in merged:speech|=(times>=a)&(times<=b)
    env=np.where(speech,-opts['speech_duck_db'],0.)+base
    for i in np.flatnonzero(active):
        a=i*25;b=min(count,(i+1)*25)
        env[a:b]=np.minimum(env[a:b],vr[i]-mr[i]-opts['target_gap_db'])
    for i in range(1,count):env[i]=min(env[i],env[i-1]+opts['recovery_db_per_second']/50)
    for i in range(count-2,-1,-1):env[i]=min(env[i],env[i+1]+opts['descent_db_per_second']/50)
    gain=np.interp(np.arange(n)/RATE,times,env).astype(np.float32)
    gain=np.power(10.,gain/20,out=gain)
    start=min(n,round(opts['fade_in_ms']/1000*RATE));end=min(n,round(opts['fade_out_ms']/1000*RATE))
    if start:gain[:start]*=np.linspace(0,1,start,dtype=np.float32)
    if end:gain[-end:]*=np.linspace(1,0,end,dtype=np.float32)
    automated=music*gain[:,None]
    return automated,{'options':opts,'active_intervals':merged,'voice_active_500ms_windows':int(active.sum()),
        'envelope_20ms':{'times_seconds':times.tolist(),'gain_db':env.tolist()}}

def _retain_old(out,old):
    if not isinstance(old.get('identity'),str)or not re.fullmatch('[0-9a-f]{64}',old['identity']):raise ValueError('Unrecognized previous music receipt; preserve it and use a new output directory')
    target=out/'history'/old['identity']
    for name in (*FILES,'original.wav','music-receipt.json'):
        source=out/name
        if not source.is_file():continue
        target.mkdir(parents=True,exist_ok=True);destination=target/name
        if destination.exists():
            if sha(source)!=sha(destination):raise RuntimeError('Different historical music files share an identity; preserve and inspect them')
        else:shutil.copy2(source,destination)

def create(dialogue,cues,out,options=None,*,base_dir=None,root=ROOT,runtime_overrides=None,ffmpeg=None):
    dialogue=Path(dialogue).resolve();out=Path(out).resolve();root=Path(root).resolve()
    compatible=legacy_cache(dialogue,cues,out,options,root=root)
    if compatible:return compatible
    spec=source_spec(options,base_dir);mode=spec['mode'];ff=_ffmpeg(root,ffmpeg)
    with wave.open(str(dialogue))as stream:
        n=stream.getnframes()
        if stream.getframerate()!=RATE:raise ValueError('Narration must be a 48 kHz WAV before BGM mixing')
    source=None;render=None
    if mode=='score':
        if not spec.get('score'):raise MusicPlanRequired('Write music.score, choose supplied music.file, or explicitly choose music.mode=none')
        render=render_score(spec['score'],out/'score',root=root,runtime_overrides=runtime_overrides);source=Path(render['master'])
    elif mode=='file':
        if not spec.get('file')or not Path(spec['file']).is_file():raise MusicPlanRequired('Provide the selected music.file')
        source=Path(spec['file'])
        if spec.get('sha256')and sha(source)!=spec['sha256']:raise MusicPlanRequired('Supplied music SHA-256 differs from its plan')
    opts={**MIX_DEFAULTS,**spec.get('mix',{})}
    key=fingerprint({'version':2,'implementation':sha(__file__),'ffmpeg':digest(ff),'source':sha(source)if source else None,
        'render_identity':render['identity']if render else None,'dialogue':sha(dialogue),'cues':cues,'mix':opts,'mode':mode})
    receipt=out/'music-receipt.json';old=read(receipt)if receipt.is_file()else None
    if old and old.get('identity')==key and all((out/name).is_file()and sha(out/name)==old.get('output_sha256',{}).get(name)for name in FILES):
        return {**old,'cache_hit':True}
    targets={out/name for name in (*FILES,'original.wav')}
    if dialogue in targets or source in targets:raise ValueError('Music output files cannot also be its input; use a new output directory')
    out.mkdir(parents=True,exist_ok=True)
    if old:_retain_old(out,old)
    elif any((out/name).exists()for name in FILES):raise FileExistsError('Unrecorded music outputs exist; retain them and use a new directory')
    voice=_decode(ff,dialogue)
    if len(voice)!=n:raise ValueError('Decoded narration sample count differs from its WAV header')
    music=_decode(ff,source)if source else np.zeros_like(voice)
    if len(music)!=n:raise MusicPlanRequired(f'Music has {len(music)} samples; revise its form/tail to match narration ({n}), without silently cutting or stretching it')
    automated,automation=mix_arrays(voice,music,cues,spec.get('mix'))
    _write_pcm(out/'bgm.wav',automated)
    quantized=_decode(ff,out/'bgm.wav');mixed=voice+quantized
    if np.max(np.abs(mixed))>=10**(opts['peak_ceiling_dbtp']/20):raise ValueError('Unchanged narration plus BGM exceeds peak headroom; reduce the source music or explicitly revise the narration in a new version')
    shutil.copy2(dialogue,out/'dialogue.wav');_write_pcm(out/'mix.wav',mixed)
    if source:shutil.copy2(source,out/'original.wav')
    else:_write_pcm(out/'original.wav',music)
    mr=_rms(quantized,RATE//2);vr=_rms(voice,RATE//2);active=vr>opts['speech_window_dbfs'];gap=(vr-mr)[active]
    percentiles=np.percentile(gap,[10,50,90]).tolist()if len(gap)and source else None
    if percentiles and percentiles[0]<opts['minimum_gap_p10_db']-.05:raise ValueError('Measured narration/BGM separation is below its target')
    measurements={name:measure(ff,out/name)for name in ('dialogue.wav','bgm.wav','mix.wav')}
    if float(measurements['mix.wav']['input_tp'])>opts['peak_ceiling_dbtp']:raise ValueError('Mixed audio true peak exceeds its ceiling')
    result={'version':2,'identity':key,'mode':mode,'samples':n,'sample_rate':RATE,'cache_hit':False,
        'voice_bytes_preserved':sha(dialogue)==sha(out/'dialogue.wav'),'voice_sha256':sha(dialogue),
        'source_sha256':sha(source)if source else None,'score':render,'mix_options':opts,
        'voice_minus_music_500ms_db_percentiles_10_50_90':percentiles,
        'voice_minus_music_500ms_db_min':float(gap.min())if len(gap)and source else None,
        'active_intervals':automation['active_intervals'],'measurements':measurements,
        'mix_measurement':measurements['mix.wav'],'audition':'pending listener feedback',
        'output_sha256':{name:sha(out/name)for name in FILES}}
    write(out/'ducking-envelope.json',automation['envelope_20ms']);write(receipt,result)
    _run(ff,['-v','error','-i',out/'mix.wav','-t',min(n/RATE,48),'-c:a','libmp3lame','-b:a','192k',out/'audition.mp3'])
    return result
