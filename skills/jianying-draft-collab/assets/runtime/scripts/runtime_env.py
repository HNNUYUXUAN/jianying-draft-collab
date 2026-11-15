"""Capability-scoped local checks and real, isolated offline acceptance fixtures."""
import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(os.environ.get('JY_RUNTIME_ROOT', Path(__file__).resolve().parents[1])).resolve()
MODULES = {'requests': 'requests', 'python-dotenv': 'dotenv', 'Pillow': 'PIL',
           'PyYAML': 'yaml', 'websockets': 'websockets', 'pymediainfo': 'pymediainfo',
           'numpy': 'numpy', 'scipy': 'scipy'}
TASKS = {'local': ['core', 'media', 'font', 'music', 'native'],
         'prepare': ['core', 'media', 'font', 'music', 'native'],
         'install': ['core', 'media', 'font', 'music'],
         'music': ['core', 'media', 'music'],
         'offline': ['core', 'media', 'font'],
         'video': ['core', 'media', 'font', 'music', 'native', 'cloud_config'],
         'draft': ['core', 'media', 'native']}
TASKS['closeout'] = ['core', 'media', 'native']


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def configuration():
    path = ROOT / 'runtime-config.json'
    return read(path) if path.is_file() else {}


def configured_path(value, default=None):
    value = value or default
    if not value:
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def command(args, timeout=45, cwd=None):
    result = subprocess.run(list(map(str, args)), capture_output=True, timeout=timeout, cwd=cwd,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError(f'{Path(str(args[0])).name} exited {result.returncode}')
    return (result.stdout + result.stderr).decode('utf-8', errors='replace')


def provision_media(source=None):
    """Copy an explicitly selected, pinned source. Downloads belong to ensure_env."""
    spec = read(ROOT / 'media-toolchain.json'); dest = ROOT / 'tools/ffmpeg'
    def valid(base):
        return all((base / 'bin' / name).is_file() and digest(base / 'bin' / name) == value
                   for name, value in spec['files'].items())
    if valid(dest) and all((dest / name).is_file() for name in ('LICENSE', 'README.txt')):
        return {'status': 'reused', 'path': str(dest)}
    if dest.exists():
        raise RuntimeError('Existing media files differ; retained for review')
    base = Path(source) if source else None
    if base is None or not valid(base) or not all((base / name).is_file() for name in ('LICENSE', 'README.txt')):
        raise RuntimeError('Pinned FFmpeg source missing; run ensure_env.ps1 -Repair or provide --source')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ffmpeg-stage-', dir=dest.parent) as directory:
        stage = Path(directory); (stage / 'bin').mkdir()
        for name in spec['files']:
            shutil.copy2(base / 'bin' / name, stage / 'bin' / name)
        for name in ('LICENSE', 'README.txt'):
            shutil.copy2(base / name, stage / name)
        if not valid(stage):
            raise RuntimeError('Media copy checksum mismatch')
        stage.rename(dest)
    return {'status': 'installed', 'path': str(dest)}


def _core(config, full):
    expected = configured_path(config.get('core', {}).get('python'))
    if expected is None:
        legacy = ROOT / 'envs/jianying-draft-collab/python.exe'
        expected = legacy if legacy.is_file() else ROOT / 'envs/core/Scripts/python.exe'
    if Path(sys.executable).resolve() != expected.resolve():
        raise RuntimeError('Use the configured core interpreter through run.ps1')
    if sys.version_info[:3] != (3, 11, 16):
        raise RuntimeError('Pinned Python 3.11.16 is required')
    pins = {}
    for line in (ROOT / 'requirements-runtime.lock').read_text(encoding='utf-8').splitlines():
        match = re.match(r'^([A-Za-z0-9_.-]+)==([^;\\\s]+)', line)
        if match:
            pins[match[1]] = match[2]
    versions = {}
    for distribution, module in MODULES.items():
        version = importlib.metadata.version(distribution)
        if version != pins[distribution]:
            raise RuntimeError(f'{distribution}: expected {pins[distribution]}, found {version}')
        importlib.import_module(module); versions[distribution] = version
    if full:
        uv = configured_path(config.get('core', {}).get('uv'), 'tools/uv/uv.exe')
        if uv.is_file():
            command([uv, 'pip', 'check', '--python', sys.executable, '--no-config', '--no-cache'])
        else:
            # Legacy Conda environments may retain their own pip; no installation.
            command([sys.executable, '-m', 'pip', 'check'])
    code = {}
    for name in ['runtime_env.py']:
        path = ROOT / 'scripts' / name
        if path.is_file():
            code[name] = digest(path)
    detail = {'python': str(expected), 'version': sys.version.split()[0], 'dependencies': versions,
              'python_sha256': digest(expected), 'implementation': code}
    detail['fingerprint'] = fingerprint(detail)
    return detail


def _media(config, full):
    spec = read(ROOT / 'media-toolchain.json'); result = {}
    for name, key in [('ffmpeg.exe', 'ffmpeg'), ('ffprobe.exe', 'ffprobe')]:
        path = configured_path(config.get('media', {}).get(key), 'tools/ffmpeg/bin/' + name)
        if not path.is_file() or digest(path) != spec['files'][name]:
            raise RuntimeError(f'Pinned {name} is absent or changed')
        result[key] = {'path': str(path), 'sha256': spec['files'][name],
                       'version': command([path, '-version']).splitlines()[0]}
    ff = result['ffmpeg']['path']
    for kind, name, token in [('filter', 'subtitles', 'force_style'), ('filter', 'loudnorm', 'linear'),
                              ('filter', 'tpad', 'stop_mode'), ('encoder', 'libx264', 'libx264'),
                              ('encoder', 'libmp3lame', 'libmp3lame'), ('decoder', 'hevc', 'HEVC')]:
        if token.lower() not in command([ff, '-hide_banner', '-h', f'{kind}={name}']).lower():
            raise RuntimeError(f'Missing {kind} {name}')
    result['fingerprint'] = fingerprint(result)
    return result


def _font():
    path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if not path.is_file():
        raise RuntimeError('Microsoft YaHei is missing; add the Windows Chinese supplemental fonts before Chinese-caption tasks')
    return {'path': str(path), 'family': 'Microsoft YaHei', 'fingerprint': digest(path)}


def _native(required=None):
    from native_runtime import doctor_report
    result = doctor_report(required=required)
    if result.get('status') not in ('ready', 'passed'):
        return {'status': 'failed', 'detail': result,
                'reason': result.get('reason') or result.get('status', 'native capability is not ready')}
    implementation = {name: digest(ROOT / 'scripts' / name) for name in
                      ['native_bridge.py', 'native_runtime.py', 'native_probe.py', 'draft_backend.py']
                      if (ROOT / 'scripts' / name).is_file()}
    return {'status': 'passed', 'detail': result,
            'fingerprint': fingerprint({'identity': result.get('identity', result.get('fingerprint', result)),
                                        'implementation': implementation})}


def _music(spec):
    from music_adapter import doctor
    result = doctor(spec, root=ROOT)
    if result.get('status') != 'passed':
        return {'status': 'failed', 'detail': result, 'reason': result.get('reason', 'Music environment is not ready')}
    implementation = {name: digest(ROOT / 'scripts' / name) for name in
                      ['music.py', 'music_v2.py', 'music_adapter.py', 'music_fixtures.py']
                      if (ROOT / 'scripts' / name).is_file()}
    return {'status': 'passed', 'detail': result,
            'fingerprint': fingerprint({'engine': result.get('fingerprint', fingerprint(result)),
                                        'implementation': implementation})}


def _cloud():
    from pipeline import config
    values = config(); present = bool(values.get('VOLC_AGENT_API_KEY'))
    return {'status': 'configured_unverified' if present else 'missing_configuration',
            'detail': {'configured': present, 'configuration_file': str(ROOT / '.env'),
                       'tts': values.get('TTS_MODEL'), 'asr': values.get('ASR_MODEL'),
                       'vision': values.get('VISION_MODEL'), 'auth_verified': False},
            'reason': None if present else 'Dedicated VOLC_AGENT_API_KEY is missing'}


def doctor(full=False, *, task='local', required=None, music=None, require_smoke=True):
    """Read-only checks. A passing cached smoke is bound to current capabilities."""
    config = configuration(); required = list(TASKS[task] if required is None else required)
    if music and music.get('mode') in ('none', 'file'):
        required = [name for name in required if name != 'music']
    checks = []; components = {}
    functions = {'core': lambda: _core(config, full), 'media': lambda: _media(config, full),
                 'font': _font, 'native': lambda: _native(['read'] if task == 'closeout' else None),
                 'music': lambda: _music(music), 'cloud_config': _cloud}
    # Observe configuration state too, but only selected capabilities gate readiness.
    for name in dict.fromkeys(required + ['cloud_config']):
        if name not in functions:
            checks.append({'name': name, 'status': 'failed', 'reason': 'Unknown required capability'}); continue
        try:
            detail = functions[name]()
            if isinstance(detail, dict) and 'status' in detail:
                item = {'name': name, **detail}
            else:
                item = {'name': name, 'status': 'passed', 'detail': detail}
            checks.append(item)
            if item['status'] == 'passed':
                components[name] = item.get('fingerprint') or fingerprint(item['detail'])
        except Exception as error:
            checks.append({'name': name, 'status': 'failed', 'error_type': type(error).__name__, 'reason': str(error)})
    smoke_required = require_smoke and task not in ('closeout', 'install')
    if task == 'closeout':
        smoke = {'status': 'not_required', 'scope': 'closeout_read_and_media_checks',
                 'reason': 'Closeout checks the current native read probe and media tools; final export decoding is performed by the closeout operation'}
    elif task == 'install':
        smoke = {'status': 'not_required', 'scope': 'installation_tool_checks',
                 'reason': 'Installation verifies the pinned tools; run local or full env smoke before creating music or video'}
    else:
        smoke = {'status': 'not_checked'}
    if smoke_required:
        smoke = {'status': 'missing', 'remedy': 'Run env smoke (or --local-only for installation capabilities)'}
        candidates = []
        # A subsequent local-only check must not replace still-current native
        # integration evidence. Each candidate must independently cover the task.
        for cache_path in [ROOT / 'state/smoke-full.json', ROOT / 'state/smoke-local.json', ROOT / 'state/smoke-latest.json']:
            if not cache_path.is_file():
                continue
            try:
                cache = read(cache_path)
                local_required = [name for name in required if name != 'cloud_config']
                matching = all(name in cache.get('capabilities', []) and name in components
                               and cache.get('fingerprints', {}).get(name) == components[name]
                               for name in local_required)
                artifacts = cache.get('artifacts', [])
                intact = bool(artifacts) and all(Path(row['path']).is_file() and digest(row['path']) == row['sha256']
                                                 for row in artifacts)
                candidate = {'status': 'passed' if matching and intact else 'stale',
                         'capabilities': cache.get('capabilities', []), 'report': cache.get('report'),
                         'configuration_matches': matching, 'artifacts_intact': intact,
                         'receipt': str(cache_path)}
                candidates.append(candidate)
                if candidate['status'] == 'passed':
                    smoke = candidate
                    break
            except Exception as error:
                candidates.append({'status': 'stale', 'reason': str(error), 'receipt': str(cache_path)})
        if smoke['status'] != 'passed' and candidates:
            smoke = {'status': 'stale', 'candidates': candidates,
                     'remedy': 'Run env smoke after a successful draft probe for native tasks'}
        checks.append({'name': 'smoke_cache', 'status': smoke['status'], 'detail': smoke})
    accepted = ('passed', 'configured_unverified')
    failed = [item['name'] for item in checks if item['name'] in required and item['status'] not in accepted]
    if smoke_required and smoke['status'] != 'passed':
        failed.append('smoke_cache')
    return {'ready': not failed, 'local_ready': not failed, 'task': task, 'required': required,
            'checks': checks, 'failed': failed, 'fingerprints': components, 'smoke': smoke,
            'api_called': False, 'desktop_actions': 0, 'cloud_auth': 'not_tested',
            'host_browser': {'status': 'requires_host_check', 'note': 'Connection, login, Create image and original download require separate host evidence'}}


def preflight(project=None, *, task='video', music=None, required=None, full=False):
    if music is None and project is not None:
        plan = Path(project) / 'production-plan.json'
        if plan.is_file():
            music = read(plan).get('music')
    return doctor(full, task=task, required=required, music=music, require_smoke=True)


def smoke(out, local_only=False):
    """Render public synthetic evidence; never register a project or use cloud APIs."""
    required = TASKS['install'] if local_only else TASKS['local']
    initial = doctor(full=True, required=required, require_smoke=False)
    if not initial['ready']:
        raise RuntimeError('Smoke prerequisites failed: ' + ', '.join(initial['failed']))
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=False)
    import numpy as np
    from pipeline import wav
    from music_adapter import example_score_path
    from music import create
    score_path = example_score_path(); score = read(score_path)
    seconds = score['clock']['bars'] * score['clock']['meter'][0] * 60 / score['clock']['tempo'][0][1] + score['clock']['tail_seconds']
    rate = 48000; times = np.arange(round(rate * seconds)) / rate
    # A deliberately identified tone stands in for speech; no ASR/TTS claim.
    voice = (np.sin(2 * np.pi * 330 * times) * .18 * (((times > .3) & (times < 2.3)) | ((times > 4) & (times < 6.5)))).astype(np.float64)
    wav(out / 'voice.wav', rate, (voice * 32767).astype('<i2').tobytes())
    cues = [{'text': '离线环境检查', 'start_ms': 300, 'end_ms': 2300}, {'text': '合成测试夹具', 'start_ms': 4000, 'end_ms': 6500}]
    music = create(out / 'voice.wav', cues, out / 'music', {'mode': 'score', 'score': str(score_path)})
    (out / 'captions.srt').write_text('1\n00:00:00,300 --> 00:00:02,300\n离线环境检查\n\n2\n00:00:04,000 --> 00:00:06,500\n合成测试夹具\n', encoding='utf-8-sig')
    config = configuration(); ff = configured_path(config.get('media', {}).get('ffmpeg'), 'tools/ffmpeg/bin/ffmpeg.exe')
    command([ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc2=size=320x180:rate=30:duration={seconds}',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-map_metadata', '-1', out / 'source.mp4'])
    command([ff, '-v', 'error', '-y', '-i', 'source.mp4', '-i', 'music/mix.wav',
             '-vf', "subtitles=captions.srt:force_style='FontName=Microsoft YaHei,FontSize=20'", '-c:v', 'libx264',
             '-c:a', 'aac', '-shortest', 'preview.mp4'], cwd=out, timeout=120)
    command([ff, '-v', 'error', '-i', out / 'preview.mp4', '-f', 'null', '-'], timeout=120)
    from pymediainfo import MediaInfo
    if not any(track.track_type == 'Video' for track in MediaInfo.parse(str(out / 'source.mp4')).tracks):
        raise RuntimeError('MediaInfo cannot decode the fixture metadata')
    result = {'local_smoke': 'passed', 'capabilities': required, 'preview': str(out / 'preview.mp4'),
              'network_calls': 0, 'index_registration': False, 'desktop_actions': 0,
              'voice_fixture': 'synthetic tone; not TTS or ASR evidence', 'music': music}
    artifact_paths = [out / 'source.mp4', out / 'voice.wav', out / 'music/bgm.wav', out / 'music/mix.wav', out / 'preview.mp4']
    if not local_only:
        tracks = []
        duration = round(seconds * 1e6)
        for tid, kind, path in [('picture', 'video', 'source.mp4'), ('voice', 'audio', 'music/dialogue.wav'), ('bgm', 'audio', 'music/bgm.wav')]:
            tracks.append({'id': tid, 'type': kind, 'segments': [{'id': tid + '-01', 'path': path, 'start_us': 0, 'duration_us': duration}]})
        tracks.append({'id': 'captions', 'type': 'text', 'segments': [{'id': 'text-01', 'text': '环境检查', 'start_us': 300000, 'duration_us': 2000000}]})
        write(out / 'draft-plan.json', {'schema_version': 2, 'project': {'width': 320, 'height': 180, 'fps': 30}, 'tracks': tracks})
        command([sys.executable, ROOT / 'scripts/draft_backend.py', 'create', '--plan', out / 'draft-plan.json',
                 '--output', out / 'draft', '--destination', out / 'pending-install'], timeout=120)
        from native_bridge import validate
        from draft_backend import app_dir
        result['native'] = validate(out / 'draft', app_dir())
        artifact_paths.extend((out / 'draft').glob('Timelines/*/draft_content.json'))
        artifact_paths.append(out / 'draft/draft_content.json')
    final = doctor(full=True, required=required, require_smoke=False)
    if not final['ready'] or final['fingerprints'] != initial['fingerprints']:
        raise RuntimeError('Dependencies changed during the smoke; retain outputs and rerun')
    result['fingerprints'] = final['fingerprints']; write(out / 'smoke.json', result)
    cache = {'schema_version': 1, 'capabilities': required,
          'fingerprints': result['fingerprints'], 'report': str(out / 'smoke.json'),
          'artifacts': [{'path': str(path), 'sha256': digest(path)} for path in artifact_paths]}
    write(ROOT / ('state/smoke-local.json' if local_only else 'state/smoke-full.json'), cache)
    write(ROOT / 'state/smoke-latest.json', cache)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['doctor', 'preflight', 'provision-media', 'smoke', 'cloud-smoke'])
    parser.add_argument('--task', choices=TASKS, default='local')
    parser.add_argument('--required', nargs='+', choices=['core', 'media', 'font', 'music', 'native', 'cloud_config'])
    parser.add_argument('--full', action='store_true'); parser.add_argument('--details', action='store_true')
    parser.add_argument('--source'); parser.add_argument('--output'); parser.add_argument('--project')
    parser.add_argument('--local-only', action='store_true')
    args = parser.parse_args()
    if args.command == 'provision-media':
        result = provision_media(args.source)
    elif args.command == 'smoke':
        if not args.output:
            parser.error('--output is required for smoke')
        result = smoke(args.output, args.local_only)
    elif args.command == 'cloud-smoke':
        from cloud_smoke import run
        if not args.output:
            parser.error('--output is required for cloud-smoke')
        result = run(args.output)
    elif args.command == 'preflight':
        result = preflight(args.project, task=args.task, required=args.required, full=args.full)
    else:
        result = doctor(args.full, task=args.task, required=args.required)
    if args.output and args.command in ('doctor', 'preflight'):
        write(args.output, result)
    shown = result
    if args.command in ('doctor', 'preflight') and not args.details:
        shown = {key: value for key, value in result.items() if key not in ('checks', 'fingerprints')}
        shown['checks_passed'] = sum(item['status'] == 'passed' for item in result['checks'])
        shown['errors'] = [item for item in result['checks'] if item['name'] in result['failed']]
        if args.output:
            shown['report'] = args.output
    print(json.dumps(shown, ensure_ascii=False))
    if result.get('ready') is False or (args.command == 'cloud-smoke' and result.get('status') != 'passed'):
        sys.exit(3)


if __name__ == '__main__':
    main()
