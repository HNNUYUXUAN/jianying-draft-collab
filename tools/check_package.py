"""Offline distribution integrity, local-link and accidental private-file checks."""
from pathlib import Path
import argparse,hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--json',action='store_true');args=parser.parse_args()
    errors=[];m=json.loads((ROOT/'skill-manifest.json').read_text(encoding='utf-8-sig'));skill=ROOT/'skills'/m['skill']
    for rel,row in m['files'].items():
        p=skill/rel
        if not p.is_file()or sha(p)!=row['sha256']:errors.append('Skill hash mismatch: '+rel)
    rt=skill/'assets/runtime';rm=json.loads((rt/'runtime-manifest.json').read_text(encoding='utf-8-sig'))
    for rel,row in rm['files'].items():
        p=rt/rel
        if not p.is_file()or sha(p)!=row['sha256']:errors.append('Runtime hash mismatch: '+rel)
    checked=0
    for p in ROOT.rglob('*'):
        if not p.is_file()or any(x in p.relative_to(ROOT).parts for x in ['.git','.local','__pycache__']):continue
        if p.is_relative_to(rt) and any(x in p.relative_to(rt).parts for x in ['state','cache','envs','outputs','tools','data','config']):continue
        if p.name in {'.installation.json','runtime-config.json'}:continue
        rel=p.relative_to(ROOT).as_posix()
        if p.name=='.env' or p.suffix in ['.pyc','.pyo','.dll','.exe','.sf2','.sf3']:errors.append('Private/runtime binary in source: '+rel)
        try:text=p.read_text(encoding='utf-8-sig')
        except UnicodeError:continue
        if re.search(r'(?i)(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[\"\x27](?:sk-|[A-Za-z0-9_-]{32})[A-Za-z0-9_-]+[\"\x27]',text):errors.append('Possible literal credential: '+rel)
        if p.suffix=='.md':
            checked+=1
            for target in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)|!\[[^\]]*\]\(([^)]+)\)',text):
                link=next(x for x in target if x).strip('<>')
                if link.startswith(('http:','https:','mailto:','#'))or ' 'in link or '<'in link:continue
                link=link.split('#')[0]
                if link and not(p.parent/link).exists():errors.append('Missing local link: '+rel+' -> '+link)
    report={'passed':not errors,'skill_files':len(m['files']),'runtime_files':len(rm['files']),'markdown_files':checked,'errors':errors}
    print(json.dumps(report,ensure_ascii=False,indent=2)if args.json else str(report))
    return 0 if not errors else 1
if __name__=='__main__':sys.exit(main())
