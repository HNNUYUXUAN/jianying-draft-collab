"""Original score fixtures and non-speech PCM activity for offline numerical checks."""
from pathlib import Path
import json,wave
import numpy as np

def activity_fixture(path,seconds=12):
    """Write tones, not speech; exercises soft activity, short pauses and long observation gaps."""
    rate=48000;n=round(seconds*rate);t=np.arange(n)/rate
    data=np.zeros(n,dtype=np.float64)
    spans=[(.75,2.25,.14),(2.5,3.5,.075),(8,9.5,.11)]
    cues=[]
    for a,b,level in spans:
        a=min(a,seconds);b=min(b,seconds)
        if b<=a:continue
        start=round(a*rate);end=round(b*rate);phase=t[start:end]
        window=np.ones(end-start);ramp=min(round(.025*rate),(end-start)//2)
        window[:ramp]=np.linspace(0,1,ramp);window[-ramp:]=np.linspace(1,0,ramp)
        data[start:end]=level*(np.sin(2*np.pi*233*phase)+.2*np.sin(2*np.pi*617*phase))*window
        cues.append({'start_ms':a*1000,'end_ms':b*1000,'text':'PCM activity fixture (not speech)'})
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),'wb')as stream:
        stream.setparams((1,2,rate,0,'NONE','not compressed'));stream.writeframes(np.round(data*32767).astype('<i2').tobytes())
    return cues

def example_score(bars=12,bpm=80,tail=4):
    """A new G-major piano/marimba/string miniature; no external score or recording."""
    names=[('opening',0,4),('answer',4,4),('return',8,4)]if bars==12 else [('smoke',0,bars)]
    score={'schema':'music-production/v1','title':'A Small Clear Question'if bars==12 else'Three Instruments Offline Check',
      'version':'1.0','brief':'An original light chamber underscore. Piano asks, marimba answers and soft strings sustain the harmony. The short smoke variant checks the renderer; it is not a musical-quality test.',
      'style':{'primary':'orchestral/cinematic'},'association':{'none':'A fully specified original public installation fixture.'},
      'clock':{'bars':bars,'meter':[4,4],'tempo':[[0,bpm]],'tail_seconds':tail},
      'sections':[{'id':name,'start_bar':start,'bars':count,'intent':'A short, breathing phrase'}for name,start,count in names],
      'plan':{'identity':'A rising three-note triad and its settling answer, exchanged by piano and marimba.',
        'high_point':{'section':names[-1][0],'means':'A shared closing cadence with soft strings'},
        'sections':[{'section':name,'sounds':['piano_theme','piano_bed','marimba','strings'],'differs':'The foreground alternates while the last section closes on G.'}for name,_,_ in names]},
      'tracks':[],'harmony':[],'mix':{'chain':'bus','rules':2,'dynamics':'wide','target_lufs':-22,'range_lu':8,'c80_db':12},
      'authorship':{'method':'New note-by-note public score; no outside MIDI, song or recording.','sample_sources':'VCSL and VSCO 2 CE, CC0 recordings.'},
      'decisions':['The repeated arpeggio is a restrained accompaniment for spoken explanation; the foreground instruments alternate.',
        'sections_alike:opening+answer: The answer reverses the piano/marimba foreground order and moves through Am-D-C-G while keeping the same quiet bed for narration.',
        'sections_alike:answer+return: The piano foreground returns over Em-C-D-G; slightly warmer strings and the final held G provide a restrained cadence rather than a large density jump.']}
    def part(name,role,program,soundfont,level,pan):
        t={'id':name,'name':name,'role':role,'engine':'soundfont','soundfont':soundfont,'program':program,'bank':0,
           'range':[40,86],'notes':[],'performance':{'notes':{},'cc':[]},
           'mix':{'level_dbfs':level,'pan':pan,'highpass':45 if name=='piano_bed'else 90,'reverb_db':-19,'space':'hall'if name=='strings'else'room','width':.65}}
        if name=='strings':t['performance']['offset_ms']=-65
        score['tracks'].append(t);return t
    lead=part('piano_theme','melody',0,'vcsl',-26,-.08)
    bed=part('piano_bed','harmony',0,'vcsl',-33,-.18)
    marimba=part('marimba','countermelody',12,'vcsl',-31,.2)
    strings=part('strings','texture',49,'vsco',-38,.05)
    def add(track,bar,at,pitch,duration,velocity):
        k=sum(int(x['on']//4)==bar for x in track['notes']);nid=f'{track["id"]}_b{bar+1:03d}_n{k:03d}'
        track['notes'].append({'id':nid,'on':bar*4+at,'duration':duration,'pitch':pitch,'phrase':f'phrase_{bar//4+1}'})
        track['performance']['notes'][nid]={'velocity':velocity,'timing_ms':int(((bar*7+k*3)%9)-4),'gate':1.02}
    harmonies={'G':(43,[55,59,62]),'D':(50,[54,57,62]),'Em':(40,[52,55,59]),'C':(48,[55,60,64]),'Am':(45,[52,57,60])}
    progression=['G','D','Em','C','Am','D','C','G','Em','C','D','G']if bars==12 else ['G','Em','C','G']
    for bar in range(bars):
        name=progression[bar];bass,chord=harmonies[name];score['harmony'].append({'bar':bar+1,'symbol':name})
        add(bed,bar,0,bass,2.7,49+(bar%3)*2)
        for k,at in enumerate([.65,1.65,2.75]):add(bed,bar,at,chord[k],1.1,44+k*2+bar%2)
        target=lead if bar%4 in (0,1)else marimba
        if bars==12 and 4<=bar<8:target=marimba if bar%4 in (0,1)else lead
        pitches=[p+12 for p in chord]
        if target is marimba:pitches=[p-12 for p in pitches]
        events=[(.2,pitches[0],.9),(1.4,pitches[1],.8),(2.5,pitches[2],1.1)]if bar%2==0 else[(.3,pitches[-1],1.3),(2,pitches[1],1.4)]
        if bar==bars-1:events=[(.2,67 if target is marimba else 79,3.2)]
        for k,(at,pitch,duration)in enumerate(events):add(target,bar,at,pitch,duration,54+k*2+bar%3)
        for k,pitch in enumerate([chord[0],chord[-1]]):add(strings,bar,.35+k*.12,pitch,3.1,44+bar%3+(3 if bars==12 and bar>=8 else 0))
        for t in (lead,bed):t['performance']['cc'].extend([[bar*4,64,0],[bar*4+.1,64,85],[bar*4+3.85,64,0]])
    return score

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    for name,score in [('music-smoke-score.json',example_score(4,120,4)),('music-demo-score.json',example_score())]:
        (out/name).write_text(json.dumps(score,ensure_ascii=False,indent=2),encoding='utf-8')
