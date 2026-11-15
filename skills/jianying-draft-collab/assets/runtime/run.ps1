param([Parameter(ValueFromRemainingArguments=$true)][string[]]$PipelineArgs)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'install_support.ps1')
$config=Read-JsonMap (Join-Path $PSScriptRoot 'runtime-config.json')
$python=$null
if ($config.core.python) {
    $python=$config.core.python
    if (-not [IO.Path]::IsPathRooted($python)) { $python=Join-Path $PSScriptRoot $python }
} else {
    $legacy=Join-Path $PSScriptRoot 'envs\jianying-draft-collab\python.exe'
    if (Test-Path -LiteralPath $legacy) { $python=$legacy }
}
if (-not $python -or -not (Test-Path -LiteralPath $python)) { throw 'Core interpreter missing. Run the skill scripts/bootstrap.ps1 -Repair -RuntimeRoot <this directory>.' }
$prefix=Split-Path -Parent $python
if ((Split-Path -Leaf $prefix) -eq 'Scripts') { $prefix=Split-Path -Parent $prefix }
$media=Join-Path $PSScriptRoot 'tools\ffmpeg\bin'
if ($config.media.ffmpeg) {
    $ff=$config.media.ffmpeg
    if (-not [IO.Path]::IsPathRooted($ff)) { $ff=Join-Path $PSScriptRoot $ff }
    $media=Split-Path -Parent $ff
}
$saved=@{}
foreach($name in @('PATH','PYTHONUTF8','PYTHONIOENCODING','PYTHONDONTWRITEBYTECODE','JY_RUNTIME_ROOT','JY_NATIVE_STATE_DIR')) { $saved[$name]=[Environment]::GetEnvironmentVariable($name,'Process') }
$script='pipeline.py'
if ($PipelineArgs.Count -gt 0) {
    switch ($PipelineArgs[0]) {
        'draft' { $script='draft_backend.py'; $PipelineArgs=@($PipelineArgs | Select-Object -Skip 1) }
        'video' { $script='video.py'; $PipelineArgs=@($PipelineArgs | Select-Object -Skip 1) }
        'env' { $script='runtime_env.py'; $PipelineArgs=@($PipelineArgs | Select-Object -Skip 1) }
        'music' { $script='music.py'; $PipelineArgs=@($PipelineArgs | Select-Object -Skip 1) }
        'doctor' { $script='runtime_env.py' }
    }
}
try {
    $env:PATH="$media;$prefix;$prefix\Scripts;$prefix\Library\bin;"+$env:PATH
    $env:PYTHONUTF8='1';$env:PYTHONIOENCODING='utf-8';$env:PYTHONDONTWRITEBYTECODE='1';$env:JY_RUNTIME_ROOT=$PSScriptRoot
    if (-not $env:JY_NATIVE_STATE_DIR) { $env:JY_NATIVE_STATE_DIR=Join-Path $PSScriptRoot 'state\native-adapters' }
    & $python -X utf8 (Join-Path $PSScriptRoot ('scripts\'+$script)) @PipelineArgs
    $code=$LASTEXITCODE
} finally { foreach($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') } }
exit $code
