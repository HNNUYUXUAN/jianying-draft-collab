param([string]$RuntimeRoot,[switch]$Repair,[switch]$Rollback,[switch]$ProbeOnly,[switch]$Offline,[string]$ArchiveCache,[string]$CorePython,[string]$MediaSource,[switch]$SkipMusic)
$ErrorActionPreference='Stop'
$skillRoot=Split-Path -Parent $PSScriptRoot
$sourceRoot=Join-Path $skillRoot 'assets\runtime'
. (Join-Path $sourceRoot 'install_support.ps1')
if (-not $RuntimeRoot) { $RuntimeRoot=Join-Path $env:LOCALAPPDATA 'JianyingDraftCollab' }
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)
$receipt=Join-Path $RuntimeRoot 'state\installed.json'
$backupRoot=$RuntimeRoot+'.backups'
if ($ProbeOnly) {
    if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRoot 'run.ps1'))) {
        @{status='needs_setup';runtime_root=$RuntimeRoot;remedy='Run bootstrap.ps1 -Repair';api_called=$false} | ConvertTo-Json -Compress
        exit 3
    }
    & (Join-Path $RuntimeRoot 'run.ps1') env doctor
    exit $LASTEXITCODE
}
if ($Rollback) {
    $null=Restore-ManagedTree $RuntimeRoot $receipt $backupRoot
    & (Join-Path $RuntimeRoot 'run.ps1') env doctor
    exit $LASTEXITCODE
}
$manifest=Read-JsonMap (Join-Path $sourceRoot 'runtime-manifest.json')
$files=@{}
foreach($relative in $manifest.files.Keys) { $files[$relative]=$manifest.files[$relative].sha256 }
$files['runtime-manifest.json']=File-Sha (Join-Path $sourceRoot 'runtime-manifest.json')
$null=Install-ManagedTree $sourceRoot $RuntimeRoot $files $receipt $backupRoot
if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRoot '.env'))) { Copy-Item -LiteralPath (Join-Path $sourceRoot 'config.example.env') -Destination (Join-Path $RuntimeRoot '.env') }
if ($Repair) {
    $repairArgs=@{Repair=$true;Offline=$Offline;SkipMusic=$SkipMusic}
    if ($ArchiveCache) { $repairArgs.ArchiveCache=$ArchiveCache }
    if ($CorePython) { $repairArgs.CorePython=$CorePython }
    if ($MediaSource) { $repairArgs.MediaSource=$MediaSource }
    & (Join-Path $RuntimeRoot 'ensure_env.ps1') @repairArgs
    if ($LASTEXITCODE) { throw 'Environment preparation failed; retained installation and diagnostic files' }
}
& (Join-Path $RuntimeRoot 'run.ps1') env doctor --task install --full --output (Join-Path $RuntimeRoot 'state\environment.json')
exit $LASTEXITCODE
