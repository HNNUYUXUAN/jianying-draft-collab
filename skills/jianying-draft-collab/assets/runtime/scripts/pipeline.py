"""Bailian audio pipeline. All generated artifacts stay in the chosen output folder."""
from __future__ import annotations
import argparse
import base64
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata
import wave
from captions import display, clauses as split_clauses
import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]

def config():
    # Dedicated .env is authoritative. Never silently borrow another project's key.
    from volc_audio import DEFAULTS
    values = {**DEFAULTS, **dict(dotenv_values(ROOT / '.env'))}
    for name in set(values) | {'VOLC_AGENT_API_KEY'}:
        if name in os.environ: values[name] = os.environ[name]
    return values

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def audio(path):
    with wave.open(str(path), 'rb') as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError('Expected mono PCM16 WAV; normalize first')
        return w.getframerate(), w.readframes(w.getnframes())

def wav(path, rate, pcm):
    with wave.open(str(path), 'wb') as w:
        w.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        w.writeframes(pcm)

def normalize(source, destination, rate):
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(source),
                    '-ac', '1', '-ar', str(rate), '-c:a', 'pcm_s16le', str(destination)], check=True)

def assemble(manifest_path, out, cfg, synthesize=False, resume=False):
    manifest_path = Path(manifest_path).resolve()
    spec = read(manifest_path)
    out = Path(out).resolve()
    state = {'manifest_sha256':sha(manifest_path),'config':fingerprint({k:v for k,v in cfg.items() if 'KEY' not in k and 'SECRET' not in k})}
    if out.exists():
        if not resume or not (out/'assembly-state.json').exists() or read(out/'assembly-state.json')!=state:
            raise FileExistsError('Existing package requires --resume with unchanged manifest/config')
    segments = spec['segments']
    if not segments or len({s['id'] for s in segments}) != len(segments):
        raise ValueError('Segments must be nonempty with unique IDs')
    out.mkdir(parents=True,exist_ok=True)
    write(out/'assembly-state.json',state)
    rate = int(cfg['TTS_SAMPLE_RATE'])
    all_pcm, positions, cursor = [], [], 0
    for number, item in enumerate(segments, 1):
        if not item.get('text', '').strip():
            raise ValueError('Each narration segment needs authoritative text')
        (out / 'audit').mkdir(exist_ok=True)
        (out / 'audio').mkdir(exist_ok=True)
        raw = out / 'audit' / f'{number:02d}_speech.wav'
        if synthesize:
            tts(item['text'], raw, dict(cfg, **item.get('voice_options', {})))
        else:
            source = (manifest_path.parent / item['audio']).resolve()
            normalize(source, raw, rate)
        _, pcm = audio(raw)
        spoken_frames = len(pcm) // 2
        lead = round(float(item.get('lead_ms', 0)) * rate / 1000)
        trail = round(float(item.get('tail_ms', 0)) * rate / 1000)
        if min(lead, trail) < 0:
            raise ValueError('Negative silence is not allowed')
        needed = lead + spoken_frames + trail
        requested = round(float(item.get('slot_ms', 0)) * rate / 1000)
        if requested and requested < needed:
            raise ValueError(f'{item["id"]}: speech exceeds slot; expand timeline or revise narration, never truncate')
        total = max(needed, requested)
        padded = bytes(lead * 2) + pcm + bytes((total - lead - spoken_frames) * 2)
        target = out / 'audio' / f'{number:02d}_narration.wav'
        wav(target, rate, padded)
        positions.append({'id': item['id'], 'text': item['text'], 'audio': str(raw),
                          'import_audio': str(target), 'audio_sha256': sha(raw),
                          'start_frame': cursor, 'frames': total, 'speech_start_frame': cursor + lead,
                          'speech_frames': spoken_frames, 'sample_rate': rate,
                          'equivalences': item.get('equivalences', {})})
        all_pcm.append(padded)
        cursor += total
    wav(out / 'continuous.wav', rate, b''.join(all_pcm))
    write(out / 'placement.json', {'sample_rate': rate, 'total_frames': cursor,
                                  'segments': positions, 'master_sha256': sha(out / 'continuous.wav')})
    return out / 'placement.json'

def tts(text, destination, cfg):
    from volc_audio import tts as call
    return call(text, destination, cfg)

def asr(placement, cfg):
    from volc_audio import asr as call
    return call(placement, cfg)

def content(char):
    return unicodedata.category(char)[0] in ('L', 'N')

def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if content(c)).lower()

def tokens(response, equivalences=None):
    if 'words' in response:
        result = {'sentence': {'words': [
            {'text':w['text'],'begin_time':w['start_ms'],'end_time':w['end_ms']} for w in response['words']]}}
    else:
        result = response['output']
    sentences = result.get('sentences') or result.get('sentence') or []
    if isinstance(sentences, dict):
        sentences = [sentences]
    chars = []
    for sentence in sentences:
        for word in sentence.get('words', []):
            value = normalized(str(word['text']))
            start, end = int(word['begin_time']), int(word['end_time'])
            if start < 0 or end < start or word.get('fixed') is False:
                raise ValueError('Unstable/invalid word timestamps')
            for index, char in enumerate(value):
                chars.append({'char': char, 'start': round(start + (end-start)*index/len(value)),
                              'end': round(start + (end-start)*(index+1)/len(value)),
                              'provenance': 'native_word' if len(value)==1 else 'within_word_interpolation'})
    # Explicit user-reviewed equivalences only; record that timestamps span the original tokens.
    for before, after in (equivalences or {}).items():
        before, after = normalized(before), normalized(after)
        if not before or not after:
            raise ValueError('Empty equivalence is not permitted')
        cursor = 0
        while cursor < len(chars):
            text = ''.join(x['char'] for x in chars)
            index = text.find(before, cursor)
            if index < 0:
                break
            start, end = chars[index]['start'], chars[index+len(before)-1]['end']
            mapped = [{'char': c, 'start': round(start+(end-start)*i/len(after)),
                       'end': round(start+(end-start)*(i+1)/len(after)),
                       'provenance': 'reviewed_equivalence_interpolation'} for i,c in enumerate(after)]
            chars[index:index+len(before)] = mapped
            cursor = index + len(mapped)
    if not chars:
        raise ValueError('No word timestamps; sentence-only timing is insufficient')
    if any(a['start'] > b['start'] for a,b in zip(chars, chars[1:])):
        raise ValueError('Nonmonotonic ASR timestamps')
    return chars

def stamp(ms):
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

def align(placement, cfg):
    path = Path(placement)
    if (path.parent / 'captions.srt').exists():
        raise FileExistsError('Existing SRT preserved; create a new package version before realignment')
    data = read(path)
    cues, audit, differences = [], [], []
    split_warnings = []
    for item in data['segments']:
        if sha(item['audio']) != item['audio_sha256']:
            raise ValueError('Current WAV does not match placement')
        stored = read(Path(item['audio']).with_suffix('.asr.json'))
        if stored['audio_sha256'] != item['audio_sha256']:
            raise ValueError('ASR response belongs to different audio')
        chars = tokens(stored['response'], item.get('equivalences'))
        text = re.sub(r'\s+', '', item['text'])
        expected, actual = normalized(text), ''.join(c['char'] for c in chars)
        if expected != actual:
            differences.append({'id': item['id'], 'expected': expected, 'recognized': actual,
                                'diff': list(difflib.ndiff(expected, actual))})
            continue
        offset = round(item['speech_start_frame'] * 1000 / item['sample_rate'])
        limit = round(item['speech_frames'] * 1000 / item['sample_rate'])
        if chars[-1]['end'] > limit + 30:
            raise ValueError('ASR timestamps exceed actual speech WAV')
        audit.append({'id': item['id'], 'chars': chars, 'offset_ms': offset,
                      'equivalences': item.get('equivalences', {})})
        # Pack complete clauses first. Only split inside a clause if unavoidable, and flag it.
        clauses, cursor = [], 0
        for phrase in split_clauses(text):
            units = []
            for char in phrase:
                count = len(normalized(char))
                timing = chars[cursor:cursor+count]
                units.append((char,timing))
                cursor += count
            clauses.append(units)
        assert cursor == len(chars), 'Caption character coverage mismatch'
        buf = []
        def timed(units): return [t for _,ts in units for t in ts]
        def fits(units):
            ts=timed(units)
            return len(units)<=int(cfg['SUBTITLE_MAX_CHARS']) and (not ts or ts[-1]['end']-ts[0]['start']<=int(cfg['SUBTITLE_MAX_MS']))
        def emit(units):
            ts=timed(units)
            if ts:
                source_text=''.join(c for c,_ in units)
                cues.append({'text':display(source_text),'display_text':display(source_text),'source_text':source_text,'start_ms':offset+ts[0]['start'],'end_ms':offset+ts[-1]['end']})
        for clause in clauses:
            # Emit each semantic clause independently instead of merging then cutting a word.
            buf=[]
            for unit in clause:
                if buf and not fits(buf+[unit]):
                    split_warnings.append({'cue':len(cues)+1,'reason':'long_clause_split_needs_semantic_review'})
                    emit(buf);buf=[]
                buf.append(unit)
            emit(buf)
    write(path.parent / 'alignment-audit.json', {'segments': audit, 'differences': differences})
    if differences:
        raise ValueError('Transcript differs from narration: review alignment-audit.json; SRT not exported')
    warnings = split_warnings
    for index, cue in enumerate(cues):
        if index+1 < len(cues):
            cue['end_ms'] = min(cue['end_ms'], cues[index+1]['start_ms']-int(cfg['SUBTITLE_GAP_MS']))
        duration = cue['end_ms']-cue['start_ms']
        if duration <= 0:
            raise ValueError('ASR boundaries cannot support nonoverlapping captions')
        if duration < int(cfg['SUBTITLE_MIN_MS']) or duration > int(cfg['SUBTITLE_MAX_MS']):
            warnings.append({'cue':index+1, 'duration_ms':duration, 'reason':'manual_readability_review'})
    output = '\n\n'.join(f'{i}\n{stamp(c["start_ms"])} --> {stamp(c["end_ms"])}\n{c["text"]}' for i,c in enumerate(cues,1))+'\n'
    (path.parent/'captions.srt').write_text(output, encoding='utf-8-sig')
    write(path.parent/'caption-report.json', {'cues':cues, 'warnings':warnings,
          'ready_for_import':not warnings, 'single_line':True, 'timing_source':'ASR word timestamps with labeled interpolation'})
    return cues

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('assemble','synthesize'):
        p = sub.add_parser(command); p.add_argument('manifest'); p.add_argument('output'); p.add_argument('--resume', action='store_true')
    for command in ('asr','align'):
        p = sub.add_parser(command); p.add_argument('placement')
    sub.add_parser('doctor')
    args = parser.parse_args()
    cfg = config()
    if args.command == 'doctor':
        print(json.dumps({'provider':'volc_agent_plan', 'credential_present':bool(cfg.get('VOLC_AGENT_API_KEY')), 'tts_model':cfg['TTS_MODEL'],
                          'asr_model':cfg['ASR_MODEL'], 'api_called':False}, ensure_ascii=False)); return
    if args.command in ('assemble','synthesize'):
        print(assemble(args.manifest,args.output,cfg,args.command=='synthesize',args.resume))
    elif args.command == 'asr': asr(args.placement,cfg)
    else: print(f'cues={len(align(args.placement,cfg))}')

if __name__ == '__main__':
    main()
