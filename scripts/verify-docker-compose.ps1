param(
    [string]$ProjectName = "tripmate-agent-t014",
    [int]$RustfsHostPort = 9003,
    [int]$RustfsConsoleHostPort = 9004,
    [int]$ApiHostPort = 8000,
    [int]$McpHostPort = 8010,
    [int]$FrontendHostPort = 3000,
    [switch]$SkipBuild,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"
$dockerAvailable = $false

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    docker compose --project-name $ProjectName @Args
}

function Assert-DockerAvailable {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI를 찾을 수 없습니다. Docker Desktop을 설치하고 Windows PATH에 docker 명령이 잡히는지 확인하십시오."
    }
}

function Wait-Http {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                Write-Host "OK $Url"
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    throw "HTTP 확인 실패: $Url"
}

function Wait-Tcp {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $connect = $client.BeginConnect($HostName, $Port, $null, $null)
            if ($connect.AsyncWaitHandle.WaitOne(1000, $false)) {
                $client.EndConnect($connect)
                Write-Host "OK tcp://$HostName`:$Port"
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
        finally {
            $client.Close()
        }
    } while ((Get-Date) -lt $deadline)

    throw "TCP 확인 실패: $HostName`:$Port"
}

try {
    Assert-DockerAvailable
    $dockerAvailable = $true

    $env:RUSTFS_HOST_PORT = [string]$RustfsHostPort
    $env:RUSTFS_CONSOLE_HOST_PORT = [string]$RustfsConsoleHostPort
    $env:API_HOST_PORT = [string]$ApiHostPort
    $env:MCP_HOST_PORT = [string]$McpHostPort
    $env:FRONTEND_HOST_PORT = [string]$FrontendHostPort
    if (-not [Environment]::GetEnvironmentVariable("NEXT_PUBLIC_API_BASE_URL")) {
        $env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:$ApiHostPort"
    }

    if (-not (Test-Path ".env")) {
        Write-Host ".env 파일이 없어 Compose 기본값과 코드 기본값으로 검증합니다."
    }

    Invoke-Compose config --quiet

    if (-not $SkipBuild) {
        Invoke-Compose build api mcp scheduler frontend
    }

    Invoke-Compose up -d rustfs api mcp scheduler frontend

    Wait-Http "http://localhost:$RustfsHostPort/health/live"
    Wait-Http "http://localhost:$ApiHostPort/health"
    Wait-Http "http://localhost:$FrontendHostPort"
    Wait-Tcp "localhost" $McpHostPort

    Invoke-Compose exec -T api python /app/scripts/verify_rustfs.py
    Invoke-Compose ps
}
finally {
    if ($dockerAvailable -and -not $KeepRunning) {
        Invoke-Compose down
    }
}
