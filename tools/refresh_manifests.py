"""Refresh distribution hashes; never include generated runtimes or local records."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
SKILL=ROOT/'skills/jianying-draft-collab'
RUNTIME=SKILL/'assets/runtime'
SKIP={'.git','.local','__pycache__','envs','state','cache','outputs','tools','config','data'}
PRIVATE_NAMES={'runtime-config.json','.installation.json','installed.json'}
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def eligible(p,base):
    return p.is_file() and p.name not in PRIVATE_NAMES and not(set(p.relative_to(base).parts)&SKIP) and p.suffix not in {'.pyc','.pyo'} and not p.name.startswith('.env')
def write(p,data):p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
def main():
    manifest=RUNTIME/'runtime-manifest.json'
    old=json.loads(manifest.read_text(encoding='utf-8-sig')) if manifest.exists() else {'files':{}}
    files={}
    for p in sorted(RUNTIME.rglob('*')):
        if not eligible(p,RUNTIME) or p==manifest:continue
        rel=p.relative_to(RUNTIME).as_posix();h=sha(p);prior=old['files'].get(rel,{})
        previous=set(prior.get('previous_sha256',[]))
        if prior.get('sha256') and prior['sha256']!=h:previous.add(prior['sha256'])
        previous.discard(h)
        files[rel]={'sha256':h,'previous_sha256':sorted(previous)}
    write(manifest,{'version':'0.1.0','files':files})
    delivery=SKILL/'delivery.json'
    packaged=[p.relative_to(SKILL).as_posix()for p in sorted(SKILL.rglob('*'))if eligible(p,SKILL)and p.name not in {'delivery.json','installed.json'}]
    requirements=[
        {'id':'windows-codex','kind':'host','handling':'Windows 11 x64 with Codex and stock PowerShell; use recipient-provided host file/terminal/browser tools.'},
        {'id':'python-video','kind':'rebuild','handling':'Bootstrap locked portable Python and core dependency hashes; reuse verified configured environments.'},
        {'id':'python-music','kind':'rebuild','handling':'Independent locked music venv, pinned music-production renderer and selected CC0 VCSL/VSCO banks.'},
        {'id':'media-tools','kind':'rebuild','handling':'Download locked FFmpeg and FluidSynth from official sources; preserve notices and verify actual render/decode.'},
        {'id':'jianying','kind':'host','handling':'Recipient installs editor. Select the working installation; verify required native operations in isolated copies and cache fingerprints locally.'},
        {'id':'agent-plan','kind':'configure','handling':'Runtime .env or process variables, process first. Own credentials; configuration and real cloud validation separate. Existing audio and local music need no cloud key.'},
        {'id':'chrome-chatgpt','kind':'host','handling':'Host-connected Chrome for new explanatory images; verify login, Create image and original downloads separately.'},
        {'id':'footage-and-brief','kind':'input','handling':'User footage, intended edits and destination; preserve originals and saved user drafts.'},
    ]
    write(delivery,{'schema_version':1,'name':'jianying-draft-collab','version':'0.1.0','files':packaged,'requirements':requirements})
    distribution={p.relative_to(SKILL).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size}for p in sorted(SKILL.rglob('*'))if eligible(p,SKILL)}
    write(ROOT/'skill-manifest.json',{'schema_version':1,'version':'0.1.0','skill':'jianying-draft-collab','files':distribution})
    print(json.dumps({'runtime_files':len(files),'skill_files':len(distribution)}))
if __name__=='__main__':main()
