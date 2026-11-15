"""Device-local Jianying capability discovery and isolated acceptance.

The shipped profiles select an adapter; only a matching local receipt authorizes
production operations. No installer, desktop control or project registration.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = 1
CORE_FILES = ('JianyingPro.exe', 'vebun.exe', 'lyra-cli.exe', 'lyra_cli_client.dll', 'videoeditor.dll')
BASIC_CAPABILITIES = ('read', 'create', 'add_video', 'add_audio', 'add_text', 'text_content',
                      'text_style', 'audio_volume', 'video_volume', 'segment_move',
                      'time_range', 'segment_remove', 'blueprint')


class NativePreflightError(ValueError):
    pass


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def config():
    path = ROOT / 'runtime-config.json'
    value = read(path).get('jianying', {}) if path.is_file() else {}
    if not isinstance(value, dict):
        raise NativePreflightError('runtime-config.json: jianying must be an object')
    return value


def configured_path(value):
    path = Path(os.path.expandvars(str(value))).expanduser()
    return (ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def state_root():
    value = os.environ.get('JY_NATIVE_STATE_DIR') or config().get('state_root')
    return configured_path(value) if value else ROOT / 'state/native-adapters'


def projects_root():
    value = config().get('projects')
    if value:
        return configured_path(value)
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        raise NativePreflightError('LOCALAPPDATA missing; configure jianying.projects')
    return Path(local) / 'JianyingPro/User Data/Projects/com.lveditor.draft'


def file_version(path):
    if os.name != 'nt':
        return None
    try:
        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, data):
            return None
        pointer = ctypes.c_void_p(); length = ctypes.c_uint()
        if not version.VerQueryValueW(data, chr(92), ctypes.byref(pointer), ctypes.byref(length)):
            return None
        numbers = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))
        ms, ls = numbers[2], numbers[3]
        return '.'.join(map(str, (ms >> 16, ms & 65535, ls >> 16, ls & 65535)))
    except (OSError, AttributeError, ValueError):
        return None


def normalize_app(path):
    path = configured_path(path)
    return path.parent if path.name.lower() == 'jianyingpro.exe' else path


def complete_app(path):
    return (path / 'JianyingPro.exe').is_file() and (path / 'videoeditor.dll').is_file()


def running_apps():
    """Read process executable paths; never starts or focuses Jianying."""
    if os.name != 'nt':
        return []
    shell = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = "Get-CimInstance Win32_Process -Filter \"Name='JianyingPro.exe'\" | ForEach-Object { $_.ExecutablePath }"
    try:
        result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        return [normalize_app(line.strip()) for line in result.stdout.decode('utf-8', errors='replace').splitlines()
                if line.strip() and complete_app(normalize_app(line.strip()))]
    except (OSError, subprocess.TimeoutExpired):
        return []


def inventory(app):
    app = normalize_app(app)
    if not complete_app(app):
        raise NativePreflightError('Incomplete Jianying installation: ' + str(app))
    files = {name: {'sha256': digest(app / name), 'bytes': (app / name).stat().st_size}
             for name in CORE_FILES if (app / name).is_file()}
    value = {'app': str(app), 'version': file_version(app / 'JianyingPro.exe') or app.name,
             'folder_version': app.name, 'architecture': platform.machine(), 'files': files}
    value['fingerprint'] = hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()
    return value


def known_profile(identity):
    path = ROOT / 'native-runtime-profiles.json'
    for profile in read(path).get('profiles', []) if path.is_file() else []:
        if all(identity['files'].get(name, {}).get('sha256') == expected
               for name, expected in profile['files'].items()):
            return profile
    return None


def discover():
    found = running_apps()
    local = os.environ.get('LOCALAPPDATA')
    if local:
        folder = Path(local) / 'JianyingPro/Apps'
        found.extend(path.resolve() for path in folder.glob('*') if path.is_dir() and complete_app(path))
    return sorted(set(found), key=lambda path: str(path).lower())


def resolve_app(app=None):
    if app is not None:
        chosen = normalize_app(app)
        if not complete_app(chosen):
            raise NativePreflightError('Explicit --app is incomplete: ' + str(chosen))
        return chosen, 'explicit'
    cfg = config()
    if cfg.get('app'):
        return resolve_app(cfg['app'])[0], 'configured'
    selection = state_root() / 'selection.json'
    if selection.is_file():
        chosen = normalize_app(read(selection)['app'])
        if complete_app(chosen):
            return chosen, 'remembered'
    active = sorted(set(running_apps()))
    if len(active) == 1:
        return active[0], 'running'
    if len(active) > 1:
        raise NativePreflightError('Several Jianying installations are running; select --app explicitly')
    installed = discover()
    verified = []
    known = []
    for candidate in installed:
        identity = inventory(candidate)
        if receipt_for(identity):
            verified.append(candidate)
        elif known_profile(identity):
            known.append(candidate)
    choices, reason = (verified, 'locally_verified') if verified else (known, 'known_profile') if known else (installed, 'only_installation')
    if len(choices) == 1:
        return choices[0], reason
    if not choices:
        raise NativePreflightError('No complete Jianying installation; configure jianying.app or use --app')
    raise NativePreflightError('Several Jianying installations need selection; configure jianying.app or use --app: ' +
                               ', '.join(str(path) for path in choices))


def adapter_hash(descriptor):
    files = ['native_runtime.py', 'native_bridge.py', 'native_cli.mjs', 'draft_backend.py', 'native_local_worker.py', 'native_probe.py', 'native_verify.py']
    value = {'protocol': PROTOCOL, 'descriptor': descriptor,
             'python': {'executable': str(Path(sys.executable).resolve()), 'version': sys.version,
                        'sha256': digest(sys.executable)},
             'source_hashes': {name: digest(Path(__file__).with_name(name)) for name in files}}
    if descriptor.get('module'):
        value['module_sha256'] = digest(descriptor['module'])
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()


def descriptor_for(identity, descriptor_path=None):
    if descriptor_path:
        path = Path(descriptor_path).resolve()
        trusted = (state_root() / 'local').resolve()
        if not path.is_relative_to(trusted):
            raise NativePreflightError('Local adapters must be authored and reviewed under ' + str(trusted))
        descriptor = read(path)
        if descriptor.get('kind') == 'local_python':
            module = (path.parent / descriptor['module']).resolve()
            if not module.is_relative_to(trusted) or not module.is_file():
                raise NativePreflightError('Local adapter module must stay inside the reviewed adapter directory')
            descriptor['module'] = str(module)
        elif descriptor.get('kind') != 'bundled_lyra':
            raise NativePreflightError('Unknown local adapter kind')
    else:
        descriptor = {'id': 'bundled_lyra', 'kind': 'bundled_lyra', 'host': 'vebun.exe', 'cli': 'lyra-cli.exe'}
    for field in ['host', 'cli']:
        if field not in descriptor:
            continue
        path = Path(descriptor[field])
        if path.is_absolute() or '..' in path.parts or ':' in str(path):
            raise NativePreflightError('Adapter executable must be relative to the selected app')
        if not (Path(identity['app']) / path).is_file():
            raise NativePreflightError('Missing installed adapter executable: ' + str(path))
    return descriptor


def receipt_for(identity):
    path = state_root() / identity['fingerprint'] / 'receipt.json'
    if not path.is_file():
        return None
    try:
        value = read(path)
        if (value.get('status') != 'ready' or value.get('protocol') != PROTOCOL or value.get('identity') != identity or
                value.get('adapter_sha256') != adapter_hash(value['adapter'])):
            return None
        return value
    except (OSError, ValueError, KeyError):
        return None


def doctor_report(app=None, required=None):
    required = list(required or ['read', 'create'])
    try:
        chosen, reason = resolve_app(app)
        identity = inventory(chosen)
        receipt = receipt_for(identity)
        capabilities = receipt.get('capabilities', {}) if receipt else {}
        missing = [name for name in required if capabilities.get(name) != 'passed']
        known = known_profile(identity)
        return {'status': 'ready' if not missing else 'needs_probe' if known or all(name in identity['files'] for name in CORE_FILES[1:]) else 'needs_local_adapter',
                'identity': identity, 'selected_by': reason, 'known_profile': known.get('version') if known else None,
                'capabilities': capabilities, 'required': required, 'missing': missing,
                'evidence': receipt.get('evidence') if receipt else None,
                'actions': [] if not missing else ['Run native_runtime.py probe --output NEW_PRIVATE_DIRECTORY --app ' + str(chosen),
                                                    'If the isolated probe fails, inspect the installed help/logs and follow references/compatibility.md']}
    except (NativePreflightError, OSError, ValueError) as error:
        return {'status': 'failed', 'required': required, 'capabilities': {}, 'reason': str(error),
                'actions': ['Select a complete installed Jianying path; no app upgrade/downgrade is performed']}


def require(app, capability):
    identity = inventory(app)
    receipt = receipt_for(identity)
    if not receipt or receipt.get('capabilities', {}).get(capability) != 'passed':
        raise NativePreflightError('native_preflight_required: ' + capability + '; run the isolated native probe for this app/adapter fingerprint')
    return receipt


def capability_for(args):
    command = tuple(args[:3])
    if command[:2] == ('draft', 'extract'):
        return 'read'
    if command == ('draft', 'project', 'create'):
        return 'create'
    if len(command) >= 3 and command[0] == 'draft':
        group, action = command[1:]
        if group == 'blueprint' and action in ['init', 'sync', 'plan', 'apply']:
            return 'blueprint'
        if action == 'add' and group in ['video', 'audio', 'text']:
            return 'add_' + group
        names = {('text', 'content'): 'text_content', ('text', 'style'): 'text_style',
                 ('audio', 'volume'): 'audio_volume', ('video', 'volume'): 'video_volume',
                 ('segment', 'move'): 'segment_move', ('segment', 'time-range'): 'time_range',
                 ('segment', 'remove'): 'segment_remove', ('text', 'remove'): 'segment_remove'}
        if (group, action) in names:
            return names[(group, action)]
    raise NativePreflightError('Native command has no verified capability mapping')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['doctor', 'inventory', 'probe'])
    parser.add_argument('--app'); parser.add_argument('--output', type=Path)
    parser.add_argument('--adapter', type=Path)
    args = parser.parse_args()
    if args.command == 'doctor':
        result = doctor_report(args.app)
    elif args.command == 'inventory':
        chosen, reason = resolve_app(args.app); result = dict(inventory(chosen), selected_by=reason)
    else:
        if not args.output:
            parser.error('probe requires a new private --output directory')
        from native_probe import probe
        result = probe(args.output, args.app, args.adapter)
    print(json.dumps(result, ensure_ascii=True))
    if result.get('status') in ['failed', 'needs_local_adapter']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
