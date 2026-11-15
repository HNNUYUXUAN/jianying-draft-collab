param([switch]$Repair,[switch]$Offline,[string]$ArchiveCache,[string]$CorePython,[string]$MediaSource,[switch]$SkipMusic,[switch]$SkipSmoke)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'install_support.ps1')
if (-not $Repair) { & (Join-Path $PSScriptRoot 'run.ps1') env doctor; exit $LASTEXITCODE }
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Windows x64 is required' }
if (-not $ArchiveCache) { $ArchiveCache=Join-Path $PSScriptRoot 'cache\downloads' }
$ArchiveCache=[IO.Path]::GetFullPath($ArchiveCache)
$lock=Read-JsonMap (Join-Path $PSScriptRoot 'environment-lock.json')
if ($lock.budget) {
    Write-Host ('Installation budget: about {0:N0} MB pinned archives + {1:N0} MB Python wheels; keep {2:N1} GB free for runtime/cache. Existing verified downloads are reused. Jianying and user projects are separate.' -f ($lock.budget.pinned_archives_download_bytes/1000000),($lock.budget.python_wheels_estimated_bytes/1000000),($lock.budget.recommended_free_bytes/1000000000))
}
$configPath=Join-Path $PSScriptRoot 'runtime-config.json'
$config=Read-JsonMap $configPath
if (-not $config.schema_version) { $config.schema_version=1 }
foreach($key in @('core','media','music','jianying')) { if (-not $config.ContainsKey($key)) { $config[$key]=@{} } }
function Resolve-ConfigPath([string]$Value) {
    if (-not $Value) { return $null }
    if ([IO.Path]::IsPathRooted($Value)) { return [IO.Path]::GetFullPath($Value) }
    return [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $Value))
}
function Run-Checked([string]$Executable,[string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE) { throw ('Command failed: '+[IO.Path]::GetFileName($Executable)+' (exit '+$LASTEXITCODE+')') }
}
function Check-Python([string]$Candidate) {
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
    $version=& $Candidate -I -c "import sys;print('.'.join(map(str,sys.version_info[:3])))" 2>$null
    return ($LASTEXITCODE -eq 0 -and $version -eq $lock.python_version)
}
function Prepare-Venv([string]$Target,[string]$Base,[string]$Requirements,[switch]$ExistingExternal) {
    if ($ExistingExternal) {
        if (-not (Check-Python $Target)) { throw 'Existing core interpreter must be the pinned Python version' }
        # External/Conda environments are reused in place without pip sync/removal.
        Run-Checked $Target @('-X','utf8','-c',"import importlib.metadata as m;from pathlib import Path;p=Path(r'$Requirements');pins=[s.strip() for s in p.read_text().splitlines() if '==' in s and not s.startswith('#')];assert all(m.version(s.split('==')[0])==s.split('==')[1] for s in pins)")
        Run-Checked $uv @('pip','check','--python',$Target,'--no-config')
        return $Target
    }
    $prefix=Split-Path -Parent (Split-Path -Parent $Target)
    $marker=Join-Path $prefix '.jianying-managed-venv.json'
    if (Test-Path -LiteralPath $prefix) {
        if (-not (Test-Path -LiteralPath $marker)) { throw "Unowned environment exists; retained: $prefix" }
        if (-not (Test-Path -LiteralPath $Target -PathType Leaf) -or (File-Sha $Target) -ne $lock.venv_python_sha256) { throw "Managed venv launcher is missing or changed; retained: $Target" }
        if (-not (Check-Python $Target)) { throw "Environment interpreter is incomplete or has changed; retained: $prefix" }
    } else {
        Run-Checked $uv @('venv','--python',$Base,'--no-python-downloads','--no-config',$prefix)
        if ((File-Sha $Target) -ne $lock.venv_python_sha256) { throw 'New managed venv launcher differs from its pinned build' }
        Write-JsonFile $marker @{schema_version=1;python_version=$lock.python_version;created_by='jianying-draft-collab'}
    }
    $syncArgs=@('pip','sync','--python',$Target,'--require-hashes','--default-index','https://pypi.org/simple','--no-config',$Requirements)
    if ($Offline) { $syncArgs+='--offline' }
    Run-Checked $uv $syncArgs
    Run-Checked $uv @('pip','check','--python',$Target,'--no-config')
    return $Target
}
$saved=@{}
foreach($name in @('UV_CACHE_DIR','UV_NO_CONFIG','UV_PYTHON_DOWNLOADS','UV_PYTHON_INSTALL_DIR','PYTHONUTF8','PYTHONIOENCODING','UV_SYSTEM_CERTS','HTTP_PROXY','HTTPS_PROXY')) { $saved[$name]=[Environment]::GetEnvironmentVariable($name,'Process') }
try {
    if (-not $env:HTTPS_PROXY -and -not $env:HTTP_PROXY -and -not $env:ALL_PROXY) {
        $destination=[Uri]'https://pypi.org/simple/'
        $proxy=Get-DownloadProxy $destination
        if ($proxy) {
            $address=$proxy.GetProxy($destination)
            if ($address -and $address.Host -ne $destination.Host) { $env:HTTP_PROXY=$address.AbsoluteUri;$env:HTTPS_PROXY=$address.AbsoluteUri }
        }
    }
    $env:UV_CACHE_DIR=Join-Path $ArchiveCache 'uv-cache'
    $env:UV_NO_CONFIG='1';$env:UV_PYTHON_DOWNLOADS='never';$env:UV_PYTHON_INSTALL_DIR=Join-Path $PSScriptRoot 'tools\python'
    $env:PYTHONUTF8='1';$env:PYTHONIOENCODING='utf-8';$env:UV_SYSTEM_CERTS='true'
    $uvArchive=Get-VerifiedDownload $lock.uv $ArchiveCache -Offline:$Offline
    $uvRoot=Join-Path $PSScriptRoot 'tools\uv'
    $uv=Join-Path $uvRoot 'uv.exe'
    if (-not (Test-Path -LiteralPath $uv)) { Expand-VerifiedZip $uvArchive $uvRoot }
    if ((File-Sha $uv) -ne $lock.uv.executable_sha256) { throw 'Portable uv executable hash mismatch; retained for inspection' }
    $uvVersion=& $uv --version
    if ($LASTEXITCODE -or $uvVersion -notmatch '^uv 0\.13\.6(?:\s|$)') { throw 'Portable uv version mismatch' }
    $config.core.uv='tools/uv/uv.exe'
    $legacy=Join-Path $PSScriptRoot 'envs\jianying-draft-collab\python.exe'
    $external=$false
    if ($CorePython) { $core=[IO.Path]::GetFullPath($CorePython);$external=$true }
    elseif ($config.core.python) {
        $core=Resolve-ConfigPath $config.core.python
        $external=-not (Test-Path -LiteralPath (Join-Path (Split-Path -Parent (Split-Path -Parent $core)) '.jianying-managed-venv.json'))
    } elseif (Test-Path -LiteralPath $legacy) { $core=$legacy;$external=$true }
    else { $core=Join-Path $PSScriptRoot 'envs\core\Scripts\python.exe' }
    if ($external) {
        if (-not (Check-Python $core)) { throw 'Existing core Python is unavailable or differs from pinned 3.11.16; no mutation performed' }
        $base=$core
    } else {
        $pythonRoot=Join-Path $PSScriptRoot 'tools\python'
        $base=Join-Path $pythonRoot 'python\python.exe'
        if (-not (Test-Path -LiteralPath $base)) {
            if (Test-Path -LiteralPath $pythonRoot) { throw "Unowned/incomplete portable Python directory retained: $pythonRoot" }
            $archive=Get-VerifiedDownload $lock.python $ArchiveCache -Offline:$Offline
            $tar=Join-Path $env:WINDIR 'System32\tar.exe'
            if (-not (Test-Path -LiteralPath $tar)) { throw 'Windows built-in tar.exe is required to unpack the pinned portable Python' }
            $members=& $tar -tzf $archive
            if ($LASTEXITCODE) { throw 'Unable to list pinned Python archive' }
            foreach($member in $members) {
                $name=$member.Replace('\','/')
                if (-not $name.StartsWith('python/') -or $name.Contains(':') -or $name.Split('/') -contains '..') { throw 'Unsafe Python archive member' }
            }
            New-Item -ItemType Directory -Path $pythonRoot -Force | Out-Null
            Run-Checked $tar @('-xzf',$archive,'-C',$pythonRoot)
        }
        if ((File-Sha $base) -ne $lock.python.executable_sha256) { throw 'Portable Python executable hash mismatch; retained for inspection' }
        if (-not (Check-Python $base)) { throw 'Portable Python version mismatch' }
    }
    $coreLock=Join-Path $PSScriptRoot 'requirements-core.lock'
    if ($external) { $coreLock=Join-Path $PSScriptRoot 'requirements-runtime.lock' }
    $null=Prepare-Venv $core $base $coreLock -ExistingExternal:$external
    if ($external) { $config.core.python=$core } else { $config.core.python='envs/core/Scripts/python.exe' }
    $config.core.python_version=$lock.python_version
    $mediaSpec=Read-JsonMap (Join-Path $PSScriptRoot 'media-toolchain.json')
    $mediaRoot=Join-Path $PSScriptRoot 'tools\ffmpeg'
    function Test-Media([string]$Directory) {
        foreach($name in $mediaSpec.files.Keys) { $f=Join-Path $Directory ('bin\'+$name);if (-not (Test-Path -LiteralPath $f) -or (File-Sha $f) -ne $mediaSpec.files[$name]) { return $false } }
        return ((Test-Path -LiteralPath (Join-Path $Directory 'LICENSE')) -and (Test-Path -LiteralPath (Join-Path $Directory 'README.txt')))
    }
    if (-not (Test-Media $mediaRoot)) {
        if (Test-Path -LiteralPath $mediaRoot) { throw "Existing media files differ; retained: $mediaRoot" }
        if ($MediaSource) {
            $source=[IO.Path]::GetFullPath($MediaSource)
            if (-not (Test-Media $source)) { throw 'MediaSource does not match pinned binaries and notices' }
        } else {
            $archive=Get-VerifiedDownload $lock.ffmpeg $ArchiveCache -Offline:$Offline
            $source=Join-Path $ArchiveCache 'ffmpeg-8.1.2-full-extracted'
            if (-not (Test-Path -LiteralPath $source)) { Expand-VerifiedZip $archive $source 'ffmpeg-8.1.2-full_build/' }
            if (-not (Test-Media $source)) { throw 'Extracted FFmpeg binary checksum mismatch' }
        }
        New-Item -ItemType Directory -Path (Join-Path $mediaRoot 'bin') -Force | Out-Null
        foreach($name in $mediaSpec.files.Keys) { Copy-Item -LiteralPath (Join-Path $source ('bin\'+$name)) -Destination (Join-Path $mediaRoot ('bin\'+$name)) }
        foreach($name in @('LICENSE','README.txt')) { Copy-Item -LiteralPath (Join-Path $source $name) -Destination (Join-Path $mediaRoot $name) }
    }
    $config.media.ffmpeg='tools/ffmpeg/bin/ffmpeg.exe';$config.media.ffprobe='tools/ffmpeg/bin/ffprobe.exe'
    Write-JsonFile $configPath $config
    if (-not $SkipMusic) {
        $musicExisting=$config.music.python -and $config.music.engine -and $config.music.config
        if ($musicExisting -and (Test-Path -LiteralPath (Resolve-ConfigPath $config.music.config))) {
            Run-Checked $core @('-X','utf8', (Join-Path $PSScriptRoot 'scripts\music_adapter.py'),'doctor','--root',$PSScriptRoot)
        } else {
            $musicPython=Join-Path $PSScriptRoot 'envs\music\Scripts\python.exe'
            $null=Prepare-Venv $musicPython $base (Join-Path $PSScriptRoot 'requirements-music.lock')
            $sourceZip=Get-VerifiedDownload $lock.music_source $ArchiveCache -Offline:$Offline
            $engine=Join-Path $PSScriptRoot 'tools\music-production'
            if (-not (Test-Path -LiteralPath $engine)) { Expand-VerifiedZip $sourceZip $engine $lock.music_source.prefix }
            $engineSpec=Read-JsonMap (Join-Path $PSScriptRoot 'music-toolchain.json')
            foreach($relative in $engineSpec.engine.files.Keys) {
                $sourceFile=Owned-Path $engine $relative
                if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf) -or (File-Sha $sourceFile) -ne $engineSpec.engine.files[$relative]) { throw "Music source differs from its pinned commit; retained: $relative" }
            }
            $upstream=Read-JsonMap (Join-Path $engine 'references\runtime-lock.json')
            $fsSpec=@($upstream.downloads | Where-Object {$_.id -eq 'fluidsynth'})[0]
            $fsArchive=Get-VerifiedDownload $fsSpec $ArchiveCache -Offline:$Offline
            $fluidRoot=Join-Path $PSScriptRoot 'tools\fluidsynth'
            if (-not (Test-Path -LiteralPath $fluidRoot)) { Expand-VerifiedZip $fsArchive $fluidRoot }
            $fluid=Join-Path $fluidRoot $fsSpec.executable
            if ((File-Sha $fluid) -ne $fsSpec.executable_sha256) { throw 'FluidSynth executable hash mismatch' }
            foreach($item in $upstream.downloads) { if ($item.id -in @('soundfont','soundfont_notice')) { $null=Get-VerifiedDownload $item $ArchiveCache -Offline:$Offline } }
            $dataRoot=Join-Path $PSScriptRoot 'data\music'
            $baseConfig=Join-Path $PSScriptRoot 'config\music-basic.json'
            $studioConfig=Join-Path $PSScriptRoot 'config\music-studio.json'
            if (Test-Path -LiteralPath $studioConfig) { throw 'Existing incomplete music configuration retained; inspect before selecting a replacement' }
            if (-not (Test-Path -LiteralPath $baseConfig)) {
                Run-Checked $musicPython @('-X','utf8',(Join-Path $engine 'scripts\bootstrap.py'),'--system','--runtime',$dataRoot,'--config',$baseConfig,'--fluidsynth',$fluid,'--ffmpeg',(Join-Path $mediaRoot 'bin\ffmpeg.exe'),'--archive-cache',$ArchiveCache,'--offline','--no-surge')
            }
            $banks=Read-JsonMap (Join-Path $engine 'references\soundbank-lock.json')
            foreach($name in @('vcsl','vsco')) {
                $item=$banks.prebuilt.assets[$name]
                $bankSpec=@{filename=$item.file;url=($banks.prebuilt.release+$item.file);sha256=$item.sha256;bytes=$item.bytes}
                $null=Get-VerifiedDownload $bankSpec $ArchiveCache -Offline:$Offline
            }
            # All required inputs have already been pinned, downloaded and checked.
            Run-Checked $musicPython @('-X','utf8',(Join-Path $engine 'scripts\fetch_soundbanks.py'),'--config',$baseConfig,'--runtime',$dataRoot,'--output',$studioConfig,'--only','vcsl,vsco','--prebuilt-from',$ArchiveCache,'--offline')
            $config.music=@{python='envs/music/Scripts/python.exe';engine='tools/music-production';config='config/music-studio.json';upstream_commit=$lock.music_source.commit}
            Write-JsonFile $configPath $config
        }
    }
    Write-JsonFile (Join-Path $PSScriptRoot 'state\environment-install.json') @{schema_version=1;python_version=$lock.python_version;core_python=$config.core.python;cache=$ArchiveCache;offline=[bool]$Offline;external_core_reused=$external;no_registry_changes=$true;global_path_unchanged=$true;cloud_calls=0}
    if (-not $SkipSmoke) {
        $stamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssffff')
        & (Join-Path $PSScriptRoot 'run.ps1') draft probe --output (Join-Path $PSScriptRoot ('state\native-probe-'+$stamp))
        $nativeProbeExit=$LASTEXITCODE
        $smokeArgs=@('env','smoke','--output',(Join-Path $PSScriptRoot ('state\smoke-'+$stamp)))
        if ($nativeProbeExit) {
            Write-JsonFile (Join-Path $PSScriptRoot 'state\native-install-status.json') @{status='requires_native_setup';probe_exit_code=$nativeProbeExit;full_video_ready=$false;remedy='Inspect draft doctor, select an installed application, then run draft probe and env smoke'}
            $smokeArgs+='--local-only'
        }
        Run-Checked (Join-Path $PSScriptRoot 'run.ps1') $smokeArgs
    }
    Run-Checked (Join-Path $PSScriptRoot 'run.ps1') @('env','doctor','--task','install','--full','--output',(Join-Path $PSScriptRoot 'state\environment.json'))
} finally {
    foreach($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') }
}
