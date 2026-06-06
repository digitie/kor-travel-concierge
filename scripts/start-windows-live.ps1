param(
    [int]$ApiPort = 9041,
    [int]$WebPort = 9042,
    [switch]$SkipRustfs
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

        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        $name = if ($process) { $process.ProcessName } else { "unknown" }
        Write-Host "포트 $Port 점유 프로세스 종료: PID=$processId NAME=$name"
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
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

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    $npmCommand = Get-Command npm -ErrorAction Stop
}
$npmPath = $npmCommand.Source

$apiUrl = "http://127.0.0.1:$ApiPort"
$webUrl = "http://127.0.0.1:$WebPort"
$vworldKey = Read-DotEnvValue -Name "NEXT_PUBLIC_VWORLD_SERVICE_KEY"

$env:NEXT_PUBLIC_API_BASE_URL = $apiUrl
$env:CORS_ALLOW_ORIGINS = "http://localhost:$WebPort,http://127.0.0.1:$WebPort"
if ($vworldKey) {
    $env:NEXT_PUBLIC_VWORLD_SERVICE_KEY = $vworldKey
}

$backendCommand = @"
Set-Location '$Root'
$pythonCommand -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port $ApiPort
"@

$frontendCommand = @"
Set-Location '$(Join-Path $Root "frontend")'
& '$npmPath' run dev -- --hostname 127.0.0.1 --port $WebPort
"@

Start-Process powershell -ArgumentList "-NoProfile", "-NoExit", "-Command", $backendCommand -WorkingDirectory $Root
Start-Process powershell -ArgumentList "-NoProfile", "-NoExit", "-Command", $frontendCommand -WorkingDirectory (Join-Path $Root "frontend")

Write-Host "TripMate API: $apiUrl"
Write-Host "TripMate Web: $webUrl"
