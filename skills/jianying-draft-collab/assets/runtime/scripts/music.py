"""Stable BGM entry point. Authored score/file/none sources and narration-first mixing."""
from music_v2 import *

def main():
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['create'])
    parser.add_argument('--dialogue',required=True,help='Existing 48 kHz narration WAV; bytes are preserved')
    parser.add_argument('--cues',required=True,help='Cue array or caption-report JSON containing cues')
    parser.add_argument('--output',required=True)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--score',help='Authored music-production/v1 score')
    source.add_argument('--file',help='Supplied music audio with the same duration as narration')
    source.add_argument('--no-music',action='store_true')
    parser.add_argument('--mix-options',help='JSON object overriding the documented narration mixing defaults')
    parser.add_argument('--root',default=str(ROOT),help='Local runtime root containing runtime-config.json')
    args=parser.parse_args()
    cues=read(args.cues)
    if isinstance(cues,dict):cues=cues['cues']
    if not isinstance(cues,list):parser.error('--cues must hold a cue array')
    spec={'mode':'score','score':args.score}if args.score else{'mode':'file','file':args.file}if args.file else{'mode':'none'}
    if args.mix_options:spec['mix']=read(args.mix_options)
    try:result=create(args.dialogue,cues,args.output,spec,root=args.root)
    except MusicPlanRequired as error:
        print(json.dumps({'status':'needs_music_plan','reason':str(error)},ensure_ascii=False));return 2
    print(json.dumps({'status':'technical_pass','mode':result.get('mode','legacy_cache'),
        'samples':result['samples'],'sample_rate':result['sample_rate'],
        'voice_bytes_preserved':result.get('voice_bytes_preserved'),
        'mix_true_peak_dbtp':result['mix_measurement']['input_tp'],
        'receipt':str(Path(args.output).resolve()/'music-receipt.json'),
        'audition':result.get('audition','historical cache retained')},ensure_ascii=False))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
