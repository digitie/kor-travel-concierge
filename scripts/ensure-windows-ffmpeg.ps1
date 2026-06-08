param(
    [string]$ArchiveUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z",
    [string]$ArchiveChecksumUrl = "",
    [string]$ArchiveSha256 = "",
    [string]$SevenZipUrl = "https://github.com/ip7z/7zip/releases/download/26.01/7zr.exe",
    [string]$SevenZipSha256 = "abcf64ae1cbafddb5395e4cdd3bdc7e3e0561d54a0c6380e3dd43bdbffe519a2",
    [string]$InstallRoot = "",
    [switch]$Force,
    [switch]$UpdateEnvFile
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
if (-not $InstallRoot) {
    $InstallRoot = Join-Path $Root ".local\ffmpeg"
}

$DownloadRoot = Join-Path $InstallRoot "downloads"
$ToolRoot = Join-Path $InstallRoot "tools"

function New-DirectoryIfMissing {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Normalize-Sha256 {
    param([string]$Value)

    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch "^[a-f0-9]{64}$") {
        throw "Invalid SHA256 value: $Value"
    }

    return $normalized
}

function Get-FileSha256 {
    param([string]$Path)

    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

function Assert-FileSha256 {
    param(
        [string]$Path,
        [string]$ExpectedSha256
    )

    if (-not $ExpectedSha256) {
        throw "SHA256 is required before using downloaded file: $Path"
    }

    $expected = Normalize-Sha256 -Value $ExpectedSha256
    $actual = Get-FileSha256 -Path $Path
    if ($actual -ne $expected) {
        throw "SHA256 mismatch for $Path. Expected $expected, actual $actual."
    }
}

function Read-RemoteSha256 {
    param(
        [string]$Url
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing
    }
    catch {
        throw "Failed to download SHA256 manifest from $Url. Pass -ArchiveSha256 or -ArchiveChecksumUrl explicitly. $($_.Exception.Message)"
    }

    $content = [string]$response.Content
    if ($content -notmatch "([A-Fa-f0-9]{64})") {
        throw "SHA256 manifest does not contain a 64-character hash: $Url"
    }

    return Normalize-Sha256 -Value $matches[1]
}

function Resolve-ArchiveSha256 {
    if ($ArchiveSha256) {
        return Normalize-Sha256 -Value $ArchiveSha256
    }

    $checksumUrl = $ArchiveChecksumUrl
    if (-not $checksumUrl) {
        $checksumUrl = "$ArchiveUrl.sha256"
    }

    return Read-RemoteSha256 -Url $checksumUrl
}

function Save-VerifiedFile {
    param(
        [string]$Url,
        [string]$Path,
        [string]$ExpectedSha256
    )

    if ((Test-Path $Path) -and -not $Force) {
        if ($ExpectedSha256) {
            $expected = Normalize-Sha256 -Value $ExpectedSha256
            $actual = Get-FileSha256 -Path $Path
            if ($actual -eq $expected) {
                return
            }

            Write-Host "Cached file hash mismatch; downloading again: $Path"
            Remove-Item $Path -Force
        }
        else {
            return
        }
    }

    if (-not $ExpectedSha256) {
        throw "SHA256 is required before downloading $Url"
    }

    New-DirectoryIfMissing -Path (Split-Path -Parent $Path)
    Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing
    Assert-FileSha256 -Path $Path -ExpectedSha256 $ExpectedSha256
}

function Expand-7ZipArchive {
    param(
        [string]$ArchiveTool,
        [string]$ArchivePath,
        [string]$Destination
    )

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $process = Start-Process `
            -FilePath $ArchiveTool `
            -ArgumentList @("x", "`"$ArchivePath`"", "`"-o$Destination`"", "-y") `
            -Wait `
            -PassThru `
            -NoNewWindow `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath
        if ($process.ExitCode -ne 0) {
            $stderr = (Get-Content $stderrPath -Raw -ErrorAction SilentlyContinue).Trim()
            $stdout = (Get-Content $stdoutPath -Raw -ErrorAction SilentlyContinue).Trim()
            $details = @($stderr, $stdout) | Where-Object { $_ } | Select-Object -First 1
            if (-not $details) {
                $details = "no output"
            }
            throw "FFmpeg archive extraction failed with exit code $($process.ExitCode): $details"
        }
    }
    finally {
        Remove-Item $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Find-ProjectExecutable {
    param([string]$Name)

    if (-not (Test-Path $InstallRoot)) {
        return $null
    }

    $found = Get-ChildItem -Path $InstallRoot -Filter "$Name.exe" -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*\bin\$Name.exe" } |
        Sort-Object FullName |
        Select-Object -First 1

    if ($found) {
        return $found.FullName
    }

    return $null
}

function Resolve-ArchiveTool {
    foreach ($name in @("7z.exe", "7za.exe", "7zr.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    foreach ($candidate in @(
        "C:\Program Files\7-Zip\7z.exe",
        "C:\Program Files (x86)\7-Zip\7z.exe"
    )) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $portable7z = Join-Path $ToolRoot "7zr.exe"
    Save-VerifiedFile -Url $SevenZipUrl -Path $portable7z -ExpectedSha256 $SevenZipSha256
    return $portable7z
}

function Format-DotEnvValue {
    param([string]$Value)

    return "'" + $Value.Replace("'", "\'") + "'"
}

function Set-DotEnvValues {
    param(
        [string]$Path,
        [hashtable]$Values
    )

    $lines = New-Object "System.Collections.Generic.List[string]"
    if (Test-Path $Path) {
        foreach ($line in Get-Content $Path) {
            [void]$lines.Add($line)
        }
    }

    foreach ($key in $Values.Keys) {
        $formattedValue = Format-DotEnvValue -Value ([string]$Values[$key])
        $nextLine = "$key=$formattedValue"
        $matched = $false
        for ($index = 0; $index -lt $lines.Count; $index++) {
            if ($lines[$index] -match "^\s*$([Regex]::Escape($key))\s*=") {
                $lines[$index] = $nextLine
                $matched = $true
                break
            }
        }
        if (-not $matched) {
            [void]$lines.Add($nextLine)
        }
    }

    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllLines($Path, $lines, $utf8NoBom)
}

New-DirectoryIfMissing -Path $InstallRoot
New-DirectoryIfMissing -Path $DownloadRoot

if ($Force) {
    Get-ChildItem -Path $InstallRoot -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notin @("downloads", "tools") } |
        Remove-Item -Recurse -Force
}

$ffmpegPath = Find-ProjectExecutable -Name "ffmpeg"
$ffprobePath = Find-ProjectExecutable -Name "ffprobe"

if (-not $ffmpegPath -or -not $ffprobePath) {
    $expectedArchiveSha256 = Resolve-ArchiveSha256
    $archiveUri = [Uri]$ArchiveUrl
    $archiveName = [System.IO.Path]::GetFileName($archiveUri.AbsolutePath)
    $archivePath = Join-Path $DownloadRoot $archiveName
    Save-VerifiedFile -Url $ArchiveUrl -Path $archivePath -ExpectedSha256 $expectedArchiveSha256

    $archiveTool = Resolve-ArchiveTool
    Expand-7ZipArchive -ArchiveTool $archiveTool -ArchivePath $archivePath -Destination $InstallRoot

    $ffmpegPath = Find-ProjectExecutable -Name "ffmpeg"
    $ffprobePath = Find-ProjectExecutable -Name "ffprobe"
}

if (-not $ffmpegPath -or -not $ffprobePath) {
    throw "ffmpeg.exe or ffprobe.exe was not found under $InstallRoot."
}

if ($UpdateEnvFile) {
    Set-DotEnvValues -Path (Join-Path $Root ".env") -Values @{
        FFMPEG_PATH = $ffmpegPath
        FFPROBE_PATH = $ffprobePath
    }
}

[pscustomobject]@{
    FFMPEG_PATH = $ffmpegPath
    FFPROBE_PATH = $ffprobePath
    INSTALL_DIR = (Resolve-Path $InstallRoot).Path
    ARCHIVE_URL = $ArchiveUrl
} | ConvertTo-Json -Compress
