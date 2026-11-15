"""Build a validated, portable media import folder from an approved import-plan."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import wave

def require(value, message):
    if not value:
        raise ValueError(message)

def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def cues(path, total):
    blocks = re.split(r'\n\s*\n', path.read_text(encoding='utf-8-sig').strip())
    previous = 0
    for number, block in enumerate(blocks, 1):
        lines = block.splitlines()
        require(len(lines) == 3 and int(lines[0]) == number, 'SRT must have sequential single-line cues')
        match = re.fullmatch(r'(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})', lines[1])
        require(match, 'Invalid SRT timestamp')
        values = list(map(int, match.groups()))
        start, end = [(h*3600+m*60+s)*1000+ms for h,m,s,ms in (values[:4], values[4:])]
        require(previous <= start < end <= total/1000, 'SRT overlap or out of bounds')
        require(len(lines[2]) <= 14, 'Caption exceeds 14 characters')
        previous = end
    return len(blocks)

def build(source, output):
    plan_path = source / 'import-plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8-sig'))
    require(not output.exists(), 'Choose a new output directory')
    probe = Path(sys.prefix)/'Library/bin/ffprobe.exe'
    require(probe.is_file(), 'Dedicated environment ffprobe required')
    cursor = 0
    verified = []
    for number, row in enumerate(plan['video'], 1):
        path = Path(row['file'])
        if not path.is_absolute():
            path = source/path
        require(row['number'] == number and row['start_us'] == cursor, 'Sequence gap or overlap')
        duration = row['end_us']-cursor
        require(duration > 0 and row['speed'] == 1, 'Expected pretrimmed 1x media')
        require(sha(path) == row['sha256'], 'Source hash mismatch')
        metadata = json.loads(subprocess.check_output([str(probe),'-v','error','-show_streams','-of','json',str(path)]))
        videos = [s for s in metadata['streams'] if s['codec_type']=='video']
        require(len(videos)==1 and not any(s['codec_type']=='audio' for s in metadata['streams']), 'Expected silent video')
        stream = videos[0]
        require(stream['width']==plan['width'] and stream['height']==plan['height'], 'Dimensions differ')
        require(stream['r_frame_rate']==f"{plan['fps']}/1", 'Frame rate differs')
        measured = round(float(stream['duration'])*1000000)
        require(abs(measured-duration)<=2, 'Media duration differs from EDL')
        verified.append((row,path,duration))
        cursor=row['end_us']
    require(cursor==plan['duration_us'], 'Total duration differs')
    for name in [plan['audio'],'stems/dialogue.wav','stems/bgm.wav']:
        with wave.open(str(source/name),'rb') as wav:
            require(abs(wav.getnframes()*1000000/wav.getframerate()-cursor)<=1, 'Audio duration differs')
    subtitle_count = cues(source/plan['editable_subtitles'],cursor)
    title_count = cues(source/plan['editable_title'],cursor)
    output.mkdir(parents=True)
    files = {}
    for row,path,duration in verified:
        relative = Path('video')/f"{row['number']:02d}-picture.mp4"
        destination=output/relative
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(path,destination)
        require(sha(destination)==row['sha256'], 'Copy hash mismatch')
        row['file']=relative.as_posix()
        files[relative.as_posix()]=row['sha256']
    for name in [plan['audio'],plan['editable_subtitles'],plan['editable_title'],'stems/dialogue.wav','stems/bgm.wav']:
        destination=output/name
        destination.parent.mkdir(exist_ok=True)
        if destination.suffix=='.srt':
            destination.write_text((source/name).read_text(encoding='utf-8-sig'),encoding='utf-8-sig')
        else:
            shutil.copy2(source/name,destination)
        files[name]=sha(destination)
    plan.pop('source_edl',None)
    plan['source_plan']=str(plan_path.resolve())
    (output/'import-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'timeline.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['number','file','start_us','end_us','duration_us'])
        writer.writerows((r['number'],r['file'],r['start_us'],r['end_us'],d) for r,p,d in verified)
    report={'file_validation':'passed','duration_us':cursor,'video_segments':len(verified),'subtitle_cues':subtitle_count,'title_cues':title_count,'sha256':files,'native_draft_registered':False,'in_app_validation':'pending_user_import'}
    (output/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='sha256'}))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    build(args.source.resolve(),args.output.resolve())
