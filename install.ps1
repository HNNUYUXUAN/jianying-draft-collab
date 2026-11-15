param([string]$RuntimeRoot,[string]$SkillRoot,[string]$ArchiveCache,[string]$CorePython,[string]$MediaSource,[switch]$Repair,[switch]$Offline,[switch]$ProbeOnly,[switch]$Rollback,[switch]$SkipMusic)
$ErrorActionPreference='Stop'
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Windows x64 is required' }
$sourceSkill=Join-Path $PSScriptRoot 'skills\jianying-draft-collab'
. (Join-Path $sourceSkill 'assets\runtime\install_support.ps1')
if (-not $RuntimeRoot) { $RuntimeRoot=Join-Path $env:LOCALAPPDATA 'JianyingDraftCollab' }
if (-not $SkillRoot) {
    $oldRoot=Join-Path $env:USERPROFILE '.codex\skills\jianying-draft-collab'
    $newRoot=Join-Path $env:USERPROFILE '.agents\skills\jianying-draft-collab'
    if ((Test-Path -LiteralPath $oldRoot) -and (Test-Path -LiteralPath $newRoot)) { throw 'Both legacy and current skill locations exist; pass -SkillRoot to select the installation to maintain' }
    if ((Test-Path -LiteralPath $oldRoot) -and -not (Test-Path -LiteralPath $newRoot)) { $SkillRoot=$oldRoot } else { $SkillRoot=$newRoot }
}
$RuntimeRoot=[IO.Path]::GetFullPath($RuntimeRoot);$SkillRoot=[IO.Path]::GetFullPath($SkillRoot)
$rootHash=[Security.Cryptography.SHA256]::Create()
try { $identity=([BitConverter]::ToString($rootHash.ComputeHash([Text.Encoding]::UTF8.GetBytes($SkillRoot.ToLowerInvariant())))).Replace('-','').Substring(0,16).ToLowerInvariant() } finally { $rootHash.Dispose() }
$backupRoot=Join-Path (Split-Path -Parent (Split-Path -Parent $SkillRoot)) ('skill-backups\'+$identity)
$receipt=Join-Path $SkillRoot '.installation.json'
if ($ProbeOnly) {
    & (Join-Path $sourceSkill 'scripts\bootstrap.ps1') -RuntimeRoot $RuntimeRoot -ProbeOnly
    exit $LASTEXITCODE
}
$newInstall=-not (Test-Path -LiteralPath (Join-Path $RuntimeRoot 'runtime-config.json'))
if ($Rollback) { $null=Restore-ManagedTree $SkillRoot $receipt $backupRoot }
else {
    $distribution=Read-JsonMap (Join-Path $PSScriptRoot 'skill-manifest.json')
    if ($distribution.skill -ne 'jianying-draft-collab') { throw 'Unexpected skill manifest identity' }
    $files=@{};foreach($relative in $distribution.files.Keys) { $files[$relative]=$distribution.files[$relative].sha256 }
    $null=Install-ManagedTree $sourceSkill $SkillRoot $files $receipt $backupRoot
}
$argsMap=@{RuntimeRoot=$RuntimeRoot;Repair=($Repair -or $newInstall);Offline=$Offline;Rollback=$Rollback;SkipMusic=$SkipMusic}
if ($ArchiveCache) { $argsMap.ArchiveCache=$ArchiveCache }
if ($CorePython) { $argsMap.CorePython=$CorePython }
if ($MediaSource) { $argsMap.MediaSource=$MediaSource }
& (Join-Path $SkillRoot 'scripts\bootstrap.ps1') @argsMap
$code=$LASTEXITCODE
$installed=Read-JsonMap $receipt;$installed.runtime_root=$RuntimeRoot;Write-JsonFile $receipt $installed
@{status=$(if($code -eq 0){'tools_installed'}else{'needs_attention'});skill_root=$SkillRoot;runtime_root=$RuntimeRoot;doctor_exit_code=$code;task_readiness_command='run.ps1 env doctor';api_called=$false} | ConvertTo-Json -Compress
exit $code
