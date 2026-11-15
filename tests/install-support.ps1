param([string]$Workspace)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
. (Join-Path $repo 'skills\jianying-draft-collab\assets\runtime\install_support.ps1')
if (-not $Workspace) { $Workspace=Join-Path $repo ('.local\install-support-tests\'+[guid]::NewGuid().ToString('N')) }
New-Item -ItemType Directory -Path $Workspace -Force | Out-Null
$cases=New-Object Collections.Generic.List[string]
function Assert-Test([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
function Must-Fail([scriptblock]$Action,[string]$Pattern) {
    $caught=$false;try{& $Action}catch{$caught=$_.Exception.Message -like $Pattern}
    Assert-Test $caught ('Expected failure: '+$Pattern)
}
$source=Join-Path $Workspace 'source';$dest=Join-Path $Workspace 'installed';$receipt=Join-Path $dest '.installation.json';$backups=Join-Path $Workspace 'backups'
New-Item -ItemType Directory -Path $source -Force|Out-Null
[IO.File]::WriteAllText((Join-Path $source 'a.txt'),'one')
$null=Install-ManagedTree $source $dest (Relative-FileMap $source) $receipt $backups
[IO.File]::WriteAllText((Join-Path $dest 'user.json'),'private config')
[IO.File]::WriteAllText((Join-Path $source 'a.txt'),'two')
$null=Install-ManagedTree $source $dest (Relative-FileMap $source) $receipt $backups
Assert-Test ((Get-Content -LiteralPath (Join-Path $dest 'a.txt') -Raw) -eq 'two') 'Upgrade failed'
$null=Restore-ManagedTree $dest $receipt $backups
Assert-Test ((Get-Content -LiteralPath (Join-Path $dest 'a.txt') -Raw) -eq 'one') 'Rollback failed'
Assert-Test ((Get-Content -LiteralPath (Join-Path $dest 'user.json') -Raw) -eq 'private config') 'User config changed'
$cases.Add('install_upgrade_rollback_preserve_user_configuration')
[IO.File]::WriteAllText((Join-Path $dest 'a.txt'),'user edit')
Must-Fail { $null=Install-ManagedTree $source $dest (Relative-FileMap $source) $receipt $backups } '*conflicts*'
Assert-Test ((Get-Content -LiteralPath (Join-Path $dest 'a.txt') -Raw) -eq 'user edit') 'User edit overwritten'
$cases.Add('modified_managed_file_blocks_before_mutation')
Must-Fail {$null=Owned-Path $dest '../escape.txt'} '*escapes*'
$cases.Add('managed_path_escape_blocked')

# A fake HTTPS response exercises real streaming, resumption and retry behavior;
# no test network, account, registry or browser capability is required.
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Net;
public sealed class InstallerFakeResponse : WebResponse {
    public HttpStatusCode StatusCode { get; private set; }
    private WebHeaderCollection headers = new WebHeaderCollection();
    private Stream body;
    public override WebHeaderCollection Headers { get { return headers; } }
    public InstallerFakeResponse(byte[] bytes, int status, string range, bool fail) {
        StatusCode=(HttpStatusCode)status;
        if(range!=null) headers["Content-Range"]=range;
        body=fail ? (Stream)new InstallerFailingStream() : new MemoryStream(bytes);
    }
    public override Stream GetResponseStream() { return body; }
    public override void Close() { body.Dispose(); }
}
public sealed class InstallerFailingStream : MemoryStream {
    public override int Read(byte[] buffer, int offset, int count) { throw new IOException("fixture interruption"); }
}
'@
$script:calls=0;$script:offsets=@();$script:responses=@()
function Get-PinnedDownloadResponse([Uri]$Uri,[long]$Offset,[Diagnostics.Stopwatch]$Watch) {
    $script:offsets+=$Offset;$script:calls++
    return $script:responses[$script:calls-1]
}
function Start-Sleep { param([double]$Seconds) }
$payload=[Text.Encoding]::UTF8.GetBytes('0123456789')
$payloadFile=Join-Path $Workspace 'payload.bin';[IO.File]::WriteAllBytes($payloadFile,$payload)
$spec=@{filename='fixture.bin';url='https://github.com/example/fixture';sha256=(File-Sha $payloadFile);bytes=10}
$cache=Join-Path $Workspace 'offline-cache';New-Item -ItemType Directory -Path $cache|Out-Null
[IO.File]::WriteAllBytes((Join-Path $cache 'fixture.bin'),$payload)
$null=Get-VerifiedDownload $spec $cache -Offline
Assert-Test ($script:calls -eq 0) 'Offline cache invoked network'
Must-Fail {$null=Get-VerifiedDownload $spec (Join-Path $Workspace 'missing-cache') -Offline} '*Offline archive missing*'
$cases.Add('offline_verified_cache_and_missing_cache')
[IO.File]::WriteAllText((Join-Path $cache 'fixture.bin'),'damaged')
Must-Fail {$null=Get-VerifiedDownload $spec $cache -Offline} '*checksum mismatch*'
Assert-Test ($script:calls -eq 0) 'Corrupt cache invoked network'
$cases.Add('corrupt_cache_preserved_without_network')

$cache=Join-Path $Workspace 'resume-cache';New-Item -ItemType Directory -Path $cache|Out-Null
$partial=Join-Path $cache 'fixture.bin.partial'
[IO.File]::WriteAllBytes($partial,$payload[0..3])
Write-JsonFile ($partial+'.json') @{url=$spec.url;sha256=$spec.sha256;bytes=$spec.bytes}
$script:calls=0;$script:offsets=@();$script:responses=@((New-Object InstallerFakeResponse($payload[4..9],206,'bytes 4-9/10',$false)))
$file=Get-VerifiedDownload $spec $cache
Assert-Test ((File-Sha $file) -eq $spec.sha256 -and $script:offsets[0] -eq 4) 'Range resume failed'
$cases.Add('owned_partial_resumes_using_range')

$cache=Join-Path $Workspace 'range-ignored';New-Item -ItemType Directory -Path $cache|Out-Null
$partial=Join-Path $cache 'fixture.bin.partial';[IO.File]::WriteAllBytes($partial,$payload[0..3])
Write-JsonFile ($partial+'.json') @{url=$spec.url;sha256=$spec.sha256;bytes=$spec.bytes}
$script:calls=0;$script:offsets=@();$script:responses=@((New-Object InstallerFakeResponse($payload,200,$null,$false)))
$file=Get-VerifiedDownload $spec $cache
Assert-Test ((File-Sha $file) -eq $spec.sha256) 'Range-ignore restart failed'
Assert-Test (@(Get-ChildItem -LiteralPath $cache -Filter '*.incomplete-*').Count -eq 1) 'Previous partial was not preserved'
$cases.Add('range_ignored_restarts_without_appending_full_file')

$cache=Join-Path $Workspace 'bounded-retry'
$script:calls=0;$script:offsets=@();$script:responses=@((New-Object InstallerFakeResponse($payload,200,$null,$true)),(New-Object InstallerFakeResponse($payload,200,$null,$false)))
$file=Get-VerifiedDownload $spec $cache
Assert-Test ($script:calls -eq 2 -and (File-Sha $file) -eq $spec.sha256) 'Interrupted read retry failed'
$cases.Add('interrupted_read_retries_owned_zero_length_partial')

$cache=Join-Path $Workspace 'retry-limit'
$script:calls=0;$script:offsets=@();$script:responses=@((New-Object InstallerFakeResponse($payload,200,$null,$true)),(New-Object InstallerFakeResponse($payload,200,$null,$true)),(New-Object InstallerFakeResponse($payload,200,$null,$true)))
Must-Fail {$null=Get-VerifiedDownload $spec $cache} '*after 3 attempt(s)*'
Assert-Test ($script:calls -eq 3) 'Network failure exceeded retry bound'
Assert-Test (Test-Path -LiteralPath (Join-Path $cache 'fixture.bin.partial')) 'Interrupted partial was lost'
$cases.Add('network_failure_stops_after_three_attempts')

# Exercise the installer entry point with a real verified cache and a modified
# would-be executable. It must fail at the SHA gate, before version execution.
$gate=Join-Path $Workspace 'executable-gate';$gateCache=Join-Path $gate 'cache';$gatePackage=Join-Path $gate 'archive-source'
New-Item -ItemType Directory -Path $gateCache,$gatePackage,(Join-Path $gate 'tools\uv') -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $gatePackage 'uv.exe'),'pinned fixture bytes')
Add-Type -AssemblyName System.IO.Compression.FileSystem
$gateArchive=Join-Path $gateCache 'uv-fixture.zip'
[IO.Compression.ZipFile]::CreateFromDirectory($gatePackage,$gateArchive)
$modifiedUv=Join-Path $gate 'tools\uv\uv.exe';[IO.File]::WriteAllText($modifiedUv,'locally modified bytes')
$before=File-Sha $modifiedUv
foreach($name in @('ensure_env.ps1','install_support.ps1')) { Copy-Item -LiteralPath (Join-Path $repo ('skills\jianying-draft-collab\assets\runtime\'+$name)) -Destination (Join-Path $gate $name) }
Write-JsonFile (Join-Path $gate 'environment-lock.json') @{python_version='3.11.16';uv=@{filename='uv-fixture.zip';url='https://github.com/example/fixture';sha256=(File-Sha $gateArchive);bytes=(Get-Item -LiteralPath $gateArchive).Length;executable_sha256=(File-Sha (Join-Path $gatePackage 'uv.exe'))}}
$ps51=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$savedPreference=$ErrorActionPreference
try {
    $ErrorActionPreference='Continue'
    $output=& $ps51 -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $gate 'ensure_env.ps1') -Repair -Offline -ArchiveCache $gateCache 2>&1
    $code=$LASTEXITCODE
} finally { $ErrorActionPreference=$savedPreference }
Assert-Test ($code -ne 0 -and ($output -join "`n") -match 'Portable uv executable hash mismatch') 'Modified executable was not rejected before invocation'
Assert-Test ((File-Sha $modifiedUv) -eq $before) 'Modified executable was overwritten'
$cases.Add('repair_rejects_modified_tool_before_executing_it')
@{status='passed';cases=$cases.ToArray();network_calls=0;registry_changes=0} | ConvertTo-Json -Depth 5
