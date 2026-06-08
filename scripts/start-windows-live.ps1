param(
    [int]$ApiPort = 9041,
    [int]$WebPort = 9042,
    [switch]$SkipRustfs,
    [switch]$ForcePortKill
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Stop-PortOwner {
    param([int]$Port)

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    $processIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($processId in $processIds) {
        if (-not $processId -or $processId -eq $PID) {
            continue
        }

        $processInfo = Get-ProcessInfo -ProcessId $processId
        $name = if ($processInfo.Name) { $processInfo.Name } else { "unknown" }
        if (-not $ForcePortKill -and -not (Test-TripMateProcess -ProcessInfo $processInfo)) {
            throw "포트 $Port 점유 프로세스가 현재 워크트리 프로세스로 확인되지 않아 종료하지 않았습니다. PID=$processId NAME=$name. 직접 종료하거나 -ForcePortKill 옵션을 명시하세요."
        }

        $reason = if ($ForcePortKill) { "강제 옵션" } else { "현재 워크트리 프로세스" }
        Write-Host "포트 $Port 점유 프로세스 종료($reason): PID=$processId NAME=$name"
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

function Get-ProcessInfo {
    param([int]$ProcessId)

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    $cimProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue

    return [pscustomobject]@{
        Id = $ProcessId
        Name = if ($process) { $process.ProcessName } else { $null }
        Path = if ($process) { $process.Path } else { $null }
        CommandLine = if ($cimProcess) { $cimProcess.CommandLine } else { $null }
    }
}

function Test-TripMateProcess {
    param([pscustomobject]$ProcessInfo)

    $rootNeedle = $Root.ToLowerInvariant()
    $values = @($ProcessInfo.Path, $ProcessInfo.CommandLine) |
        Where-Object { $_ } |
        ForEach-Object { $_.ToLowerInvariant() }

    foreach ($value in $values) {
        if ($value.Contains($rootNeedle)) {
            return $true
        }
    }

    return $false
}

function Read-DotEnvValue {
    param([string]$Name)

    $envPath = Join-Path $Root ".env"
    if (-not (Test-Path $envPath)) {
        return $null
    }

    $line = Get-Content $envPath |
        Where-Object { $_ -match "^$([Regex]::Escape($Name))=" } |
        Select-Object -First 1
    if (-not $line) {
        return $null
    }

    return ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
}

function Resolve-NodeExe {
    $candidates = @()
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($nodeCommand) {
        $candidates += $nodeCommand.Source
    }
    $candidates += @(
        "C:\Program Files\nodejs\node.exe",
        "C:\Program Files (x86)\nodejs\node.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    throw "Node.js 실행 파일을 찾을 수 없습니다. Node.js 20+ 설치 경로 또는 PATH를 확인하세요."
}

function Escape-PowerShellSingleQuotedValue {
    param([string]$Value)

    return $Value.Replace("'", "''")
}

function Test-NativeCommand {
    param(
        [string]$Path,
        [string]$Argument
    )

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $process = Start-Process `
            -FilePath $Path `
            -ArgumentList @($Argument) `
            -Wait `
            -PassThru `
            -NoNewWindow `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath
        if ($process.ExitCode -ne 0) {
            throw "외부 실행 파일 확인 실패: $Path $Argument (exit=$($process.ExitCode))"
        }
    }
    finally {
        Remove-Item $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-CorsAllowOrigins {
    param([int]$Port)

    if ($env:CORS_ALLOW_ORIGINS) {
        return $env:CORS_ALLOW_ORIGINS
    }

    $configured = Read-DotEnvValue -Name "CORS_ALLOW_ORIGINS"
    if ($configured) {
        return $configured
    }

    return @(
        "http://localhost:$Port",
        "http://127.0.0.1:$Port",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:13000",
        "http://127.0.0.1:13000",
        "http://localhost:13100",
        "http://127.0.0.1:13100"
    ) -join ","
}

Stop-PortOwner -Port $ApiPort
Stop-PortOwner -Port $WebPort

if (-not $SkipRustfs -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    Push-Location $Root
    docker compose --env-file .env up -d rustfs
    Pop-Location
}

$python = Join-Path $Root "backend\.venv\Scripts\python.exe"
$pythonCommand = if (Test-Path $python) {
    "& '$python'"
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    "& py -3.10"
}
else {
    "& python"
}

$apiUrl = "http://127.0.0.1:$ApiPort"
$webUrl = "http://127.0.0.1:$WebPort"
$vworldKey = Read-DotEnvValue -Name "NEXT_PUBLIC_VWORLD_SERVICE_KEY"
$corsAllowOrigins = Resolve-CorsAllowOrigins -Port $WebPort
$ffmpegInfoJson = & (Join-Path $Root "scripts\ensure-windows-ffmpeg.ps1") -UpdateEnvFile
$ffmpegInfo = $ffmpegInfoJson | ConvertFrom-Json
$ffmpegPath = [string]$ffmpegInfo.FFMPEG_PATH
$ffprobePath = [string]$ffmpegInfo.FFPROBE_PATH
$nodePath = Resolve-NodeExe
$nextCliPath = Join-Path $Root "frontend\node_modules\next\dist\bin\next"
if (-not (Test-Path $nextCliPath)) {
    throw "Next.js CLI를 찾을 수 없습니다. Windows에서 frontend 의존성을 먼저 설치하세요: cd frontend; npm ci"
}

$env:NEXT_PUBLIC_API_BASE_URL = $apiUrl
$env:CORS_ALLOW_ORIGINS = $corsAllowOrigins
$env:FFMPEG_PATH = $ffmpegPath
if ($vworldKey) {
    $env:NEXT_PUBLIC_VWORLD_SERVICE_KEY = $vworldKey
}

Test-NativeCommand -Path $ffmpegPath -Argument "-version"
Test-NativeCommand -Path $ffprobePath -Argument "-version"

$frontendEnv = @(
    "`$env:NEXT_PUBLIC_API_BASE_URL = '$apiUrl'"
)
$frontendEnvBlock = $frontendEnv -join "`r`n"

$backendEnv = @(
    "`$env:CORS_ALLOW_ORIGINS = '$(Escape-PowerShellSingleQuotedValue -Value $corsAllowOrigins)'",
    "`$env:FFMPEG_PATH = '$(Escape-PowerShellSingleQuotedValue -Value $ffmpegPath)'"
)
$backendEnvBlock = $backendEnv -join "`r`n"

$backendCommand = @"
Set-Location '$Root'
$backendEnvBlock
$pythonCommand -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port $ApiPort
"@

$frontendCommand = @"
Set-Location '$(Join-Path $Root "frontend")'
$frontendEnvBlock
& '$nodePath' '$nextCliPath' dev --hostname 127.0.0.1 --port $WebPort
"@

Start-Process powershell -ArgumentList "-NoProfile", "-NoExit", "-Command", $backendCommand -WorkingDirectory $Root
Start-Process powershell -ArgumentList "-NoProfile", "-NoExit", "-Command", $frontendCommand -WorkingDirectory (Join-Path $Root "frontend")

Write-Host "TripMate API: $apiUrl"
Write-Host "TripMate Web: $webUrl"
Write-Host "FFmpeg: $ffmpegPath"
