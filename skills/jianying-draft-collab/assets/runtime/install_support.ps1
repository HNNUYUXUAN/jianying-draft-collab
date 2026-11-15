$ErrorActionPreference='Stop'

function Assert-RealPath([string]$Path) {
    $candidate=[IO.Path]::GetFullPath($Path)
    while($candidate) {
        if (Test-Path -LiteralPath $candidate) {
            $item=Get-Item -LiteralPath $candidate -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Linked installation path is not supported: $candidate" }
        }
        $parent=Split-Path -Parent $candidate
        if ($parent -eq $candidate) { break }
        $candidate=$parent
    }
}
function Owned-Path([string]$Root,[string]$Relative) {
    $base=[IO.Path]::GetFullPath($Root).TrimEnd('\','/')
    $target=[IO.Path]::GetFullPath((Join-Path $base $Relative))
    if (-not $target.StartsWith($base+'\',[StringComparison]::OrdinalIgnoreCase)) { throw "Managed path escapes installation root: $Relative" }
    Assert-RealPath $target
    return $target
}

function Read-JsonMap([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return @{} }
    function Convert-Map($Value) {
        if ($null -eq $Value) { return $null }
        if ($Value -is [System.Management.Automation.PSCustomObject]) {
            $result=@{}; foreach($property in $Value.PSObject.Properties) { $result[$property.Name]=Convert-Map $property.Value }; return $result
        }
        if ($Value -is [System.Collections.IDictionary]) { return $Value }
        if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
            return ,@($Value | ForEach-Object { Convert-Map $_ })
        }
        return $Value
    }
    return Convert-Map (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}
function Write-JsonFile([string]$Path,$Value) {
    $parent=Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $temp=$Path+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
    [IO.File]::WriteAllText($temp,($Value | ConvertTo-Json -Depth 40),(New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temp -Destination $Path -Force
}
function File-Sha([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Relative-FileMap([string]$Root) {
    $map=@{}; $base=[IO.Path]::GetFullPath($Root).TrimEnd([char]92,[char]47)
    foreach($file in Get-ChildItem -LiteralPath $base -File -Recurse) {
        $relative=$file.FullName.Substring($base.Length+1).Replace([char]92,[char]47)
        if ($relative -eq '.installation.json') { continue }
        $map[$relative]=File-Sha $file.FullName
    }
    return $map
}
function Install-ManagedTree([string]$Source,[string]$Destination,[hashtable]$Files,[string]$Receipt,[string]$BackupRoot) {
    $Source=[IO.Path]::GetFullPath($Source);$Destination=[IO.Path]::GetFullPath($Destination)
    Assert-RealPath $Source;Assert-RealPath $Destination;Assert-RealPath $Receipt;Assert-RealPath $BackupRoot
    if ($Source.TrimEnd([char]92) -eq $Destination.TrimEnd([char]92)) { throw 'Source and destination must differ' }
    $previous=Read-JsonMap $Receipt
    $owned=@{}; if ($previous.ContainsKey('files')) { $owned=$previous.files }
    $conflicts=@()
    foreach($relative in $Files.Keys) {
        $sourceFile=Owned-Path $Source $relative
        if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf) -or (File-Sha $sourceFile) -ne $Files[$relative]) { throw "Source checksum mismatch: $relative" }
        $target=Owned-Path $Destination $relative
        if (Test-Path -LiteralPath $target) {
            if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { $conflicts+=$relative;continue }
            $actual=File-Sha $target
            if ($actual -ne $Files[$relative] -and (-not $owned.ContainsKey($relative) -or $actual -ne $owned[$relative])) { $conflicts+=$relative }
        }
    }
    foreach($relative in $owned.Keys) {
        if ($Files.ContainsKey($relative)) { continue }
        $target=Owned-Path $Destination $relative
        if ((Test-Path -LiteralPath $target) -and (File-Sha $target) -ne $owned[$relative]) { $conflicts+=$relative }
    }
    if ($conflicts.Count) { throw ('Managed-file conflicts; preserve these files and review: '+($conflicts -join ', ')) }
    $backup=$null
    if ($owned.Count) {
        $backup=Join-Path $BackupRoot ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssffff')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8))
        New-Item -ItemType Directory -Path $backup -Force | Out-Null
        foreach($relative in $owned.Keys) {
            $target=Owned-Path $Destination $relative
            if (Test-Path -LiteralPath $target -PathType Leaf) {
                $copy=Join-Path $backup $relative;New-Item -ItemType Directory -Path (Split-Path -Parent $copy) -Force | Out-Null
                Copy-Item -LiteralPath $target -Destination $copy
            }
        }
        Write-JsonFile (Join-Path $backup 'previous-installation.json') $previous
    }
    foreach($relative in $Files.Keys) {
        $target=Owned-Path $Destination $relative
        if ((Test-Path -LiteralPath $target -PathType Leaf) -and (File-Sha $target) -eq $Files[$relative]) { continue }
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $Source $relative) -Destination $target -Force
    }
    # Removed managed files are retained in the version backup, then removed only
    # from their exact, receipt-owned paths. Unknown local files are never listed.
    foreach($relative in $owned.Keys) {
        if ($Files.ContainsKey($relative)) { continue }
        $target=Owned-Path $Destination $relative
        if (Test-Path -LiteralPath $target -PathType Leaf) { Remove-Item -LiteralPath $target }
    }
    $record=@{schema_version=1;files=$Files;previous_backup=$backup;installed_at=[DateTime]::UtcNow.ToString('o')}
    Write-JsonFile $Receipt $record
    return $record
}
function Restore-ManagedTree([string]$Destination,[string]$Receipt,[string]$BackupRoot) {
    $current=Read-JsonMap $Receipt
    if (-not $current.previous_backup) { throw 'No previous managed version is recorded' }
    $source=[IO.Path]::GetFullPath($current.previous_backup)
    $allowed=[IO.Path]::GetFullPath($BackupRoot).TrimEnd([char]92)+[IO.Path]::DirectorySeparatorChar
    if (-not $source.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)) { throw 'Backup path is outside its owned backup directory' }
    $previous=Read-JsonMap (Join-Path $source 'previous-installation.json')
    return Install-ManagedTree $source $Destination $previous.files $Receipt $BackupRoot
}
function Get-VerifiedDownload($Spec,[string]$Cache,[switch]$Offline) {
    New-Item -ItemType Directory -Path $Cache -Force | Out-Null
    $file=Owned-Path $Cache $Spec.filename
    if (Test-Path -LiteralPath $file) {
        if ((File-Sha $file) -ne $Spec.sha256 -or ($Spec.bytes -and (Get-Item -LiteralPath $file).Length -ne $Spec.bytes)) { throw "Cached archive checksum mismatch; retained: $file" }
        return $file
    }
    if ($Offline) { throw "Offline archive missing: $file" }
    $uri=[Uri]$Spec.url
    if ($uri.Scheme -ne 'https' -or $uri.Host -notin @('github.com','codeload.github.com','raw.githubusercontent.com')) { throw 'Download URL is outside the pinned HTTPS source hosts' }
    if (-not $Spec.bytes) { throw 'A pinned download must declare its exact byte size' }
    $part=$file+'.partial';$record=$part+'.json'
    $identity=@{url=$Spec.url;sha256=$Spec.sha256;bytes=$Spec.bytes}
    if (Test-Path -LiteralPath $part) {
        $previous=Read-JsonMap $record
        if ($previous.url -ne $identity.url -or $previous.sha256 -ne $identity.sha256 -or $previous.bytes -ne $identity.bytes) { throw "Unowned partial download retained; inspect: $part" }
        if ((Get-Item -LiteralPath $part).Length -gt $Spec.bytes) { throw "Oversized partial download retained: $part" }
    } else { Write-JsonFile $record $identity }
    [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
    for($attempt=1;$attempt -le 3;$attempt++) {
        $stream=$null;$output=$null;$response=$null
        $watch=[Diagnostics.Stopwatch]::StartNew()
        try {
            if (Test-Path -LiteralPath $file) {
                if ((File-Sha $file) -eq $Spec.sha256 -and (Get-Item -LiteralPath $file).Length -eq $Spec.bytes) { return $file }
                throw [IO.InvalidDataException]::new('Completed cache checksum mismatch')
            }
            $offset=0
            if (Test-Path -LiteralPath $part) { $offset=(Get-Item -LiteralPath $part).Length }
            if ($offset -eq $Spec.bytes) {
                if ((File-Sha $part) -ne $Spec.sha256) { throw [IO.InvalidDataException]::new('Completed partial checksum mismatch; retained for inspection') }
                Move-Item -LiteralPath $part -Destination $file
                return $file
            }
            Write-Host ('Downloading {0}: {1:N0}/{2:N0} bytes, attempt {3}/3' -f $Spec.filename,$offset,$Spec.bytes,$attempt)
            $response=Get-PinnedDownloadResponse $uri $offset $watch
            $status=[int]$response.StatusCode
            if ($offset -gt 0 -and $status -eq 200) {
                # A server may ignore Range or change an object. Keep the old bytes
                # as evidence and write a new take instead of appending a full file.
                Move-Item -LiteralPath $part -Destination ($part+'.incomplete-'+[guid]::NewGuid().ToString('N'))
                $offset=0
            } elseif ($offset -gt 0 -and ($status -ne 206 -or $response.Headers['Content-Range'] -notmatch ('^bytes '+$offset+'-'))) {
                throw [IO.InvalidDataException]::new('Unexpected range response; partial retained')
            } elseif ($offset -eq 0 -and $status -ne 200) { throw [IO.InvalidDataException]::new('Unexpected download response') }
            $stream=$response.GetResponseStream()
            if ($stream.CanTimeout) { $stream.ReadTimeout=30000 }
            $mode=if($offset){[IO.FileMode]::Append}else{[IO.FileMode]::Create}
            $output=New-Object IO.FileStream($part,$mode,[IO.FileAccess]::Write,[IO.FileShare]::Read)
            $buffer=New-Object byte[] (1024*1024);$count=[long]$offset;$lastProgress=$watch.Elapsed.TotalSeconds
            while(($read=$stream.Read($buffer,0,$buffer.Length)) -gt 0) {
                $output.Write($buffer,0,$read);$count+=$read
                if ($count -gt $Spec.bytes) { throw [IO.InvalidDataException]::new('Download exceeds locked byte size') }
                if ($watch.Elapsed.TotalSeconds -gt 600) { throw [TimeoutException]::new('Download attempt duration exceeded') }
                if ($watch.Elapsed.TotalSeconds-$lastProgress -ge 20) {
                    Write-Host ('Downloading {0}: {1:N0}/{2:N0} bytes' -f $Spec.filename,$count,$Spec.bytes)
                    $lastProgress=$watch.Elapsed.TotalSeconds
                }
            }
            $output.Dispose();$output=$null;$stream.Dispose();$stream=$null;$response.Dispose();$response=$null
            if ($count -ne $Spec.bytes) { throw [IO.IOException]::new('Download ended before its locked size') }
            if ((File-Sha $part) -ne $Spec.sha256) { throw [IO.InvalidDataException]::new('Download checksum mismatch; partial retained') }
            Move-Item -LiteralPath $part -Destination $file
            Write-Host ('Verified {0}: {1:N0} bytes' -f $Spec.filename,$Spec.bytes)
            return $file
        } catch {
            $errorObject=$_.Exception
            while (($errorObject -is [Management.Automation.MethodInvocationException] -or $errorObject -is [Reflection.TargetInvocationException]) -and $errorObject.InnerException) { $errorObject=$errorObject.InnerException }
            if ($errorObject -is [IO.InvalidDataException]) { throw ('Pinned download rejected for '+$Spec.filename+': '+$errorObject.Message) }
            $retry=($errorObject -is [Net.WebException] -or $errorObject -is [IO.IOException] -or $errorObject -is [TimeoutException])
            if ($errorObject -is [Net.WebException] -and $errorObject.Response) {
                $http=[int]$errorObject.Response.StatusCode
                $errorObject.Response.Dispose()
                if ($http -ge 400 -and $http -lt 500 -and $http -notin @(408,429)) { $retry=$false }
            }
            if (-not $retry -or $attempt -eq 3) {
                # Do not echo redirect URLs, proxy credentials or complete server responses.
                throw ('Download failed for '+$Spec.filename+' after '+$attempt+' attempt(s); owned partial is retained. Error type: '+$errorObject.GetType().Name)
            }
            Write-Host ('Retrying '+$Spec.filename+' after a bounded network failure; existing partial is retained')
        } finally {
            if ($output) { $output.Dispose() };if($stream){$stream.Dispose()};if($response){$response.Dispose()};$watch.Stop()
        }
        Start-Sleep -Seconds ([Math]::Pow(2,$attempt))
    }
}

function Get-DownloadProxy([Uri]$Uri) {
    $address=$env:HTTPS_PROXY
    if (-not $address) { $address=$env:HTTP_PROXY }
    if (-not $address) { $address=$env:ALL_PROXY }
    if (-not $address) {
        $settings=Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
        if ($settings.ProxyEnable -eq 1 -and $settings.ProxyServer) {
            $address=[string]$settings.ProxyServer
            if ($address.Contains('=')) {
                $https=@($address.Split(';') | Where-Object {$_ -match '^\s*https='})
                $http=@($address.Split(';') | Where-Object {$_ -match '^\s*http='})
                $address=if($https.Count){($https[0] -split '=',2)[1]}elseif($http.Count){($http[0] -split '=',2)[1]}else{''}
            }
        }
    }
    if ($address) {
        try {
            if ($address -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://') { $address='http://'+$address.Trim() }
            return (New-Object Net.WebProxy($address))
        } catch { throw 'Configured network proxy is not a valid supported proxy URI' }
    }
    return [Net.WebRequest]::DefaultWebProxy
}
function Get-PinnedDownloadResponse([Uri]$Uri,[long]$Offset,[Diagnostics.Stopwatch]$Watch) {
    $allowed=@('github.com','codeload.github.com','raw.githubusercontent.com','release-assets.githubusercontent.com','objects.githubusercontent.com','github-releases.githubusercontent.com')
    $current=$Uri
    for($redirect=0;$redirect -le 8;$redirect++) {
        if ($current.Scheme -ne 'https' -or $current.Host -notin $allowed) { throw [IO.InvalidDataException]::new('Redirect outside pinned HTTPS source hosts') }
        if ($Watch.Elapsed.TotalSeconds -gt 600) { throw [TimeoutException]::new('Download attempt duration exceeded') }
        $request=[Net.HttpWebRequest]::Create($current)
        $request.AllowAutoRedirect=$false;$request.Timeout=45000;$request.ReadWriteTimeout=30000
        $request.UserAgent='JianyingDraftCollab-Installer/1';$request.Proxy=Get-DownloadProxy $current
        if ($Offset -gt 0) { $request.AddRange($Offset) }
        $response=$request.GetResponse()
        $status=[int]$response.StatusCode
        if ($status -in @(301,302,303,307,308)) {
            $location=$response.Headers['Location'];$response.Dispose()
            $current=New-Object Uri($current,$location)
            continue
        }
        return $response
    }
    throw [IO.InvalidDataException]::new('Download redirect limit exceeded')
}
function Expand-VerifiedZip([string]$Archive,[string]$Destination,[string]$Prefix='') {
    if (Test-Path -LiteralPath $Destination) { throw "Extraction destination exists: $Destination" }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip=[IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -gt 20000) { throw 'Archive member count exceeded' }
        foreach($entry in $zip.Entries) {
            $name=$entry.FullName.Replace([char]92,[char]47)
            if ($name.StartsWith('/') -or $name.Contains(':') -or $name.Split('/') -contains '..' -or (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) { throw 'Unsafe archive member' }
        }
        New-Item -ItemType Directory -Path $Destination | Out-Null
        foreach($entry in $zip.Entries) {
            $name=$entry.FullName.Replace([char]92,[char]47)
            if ($Prefix -and -not $name.StartsWith($Prefix,[StringComparison]::Ordinal)) { continue }
            if ($Prefix) { $name=$name.Substring($Prefix.Length) }
            if (-not $name -or $name.EndsWith('/')) { continue }
            $target=Join-Path $Destination $name
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$target,$false)
        }
    } finally { $zip.Dispose() }
}
