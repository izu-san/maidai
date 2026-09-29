<#
  MaidAI の起動ハブ
  例:
    .\Start-MaidAI.ps1                 # 会話用（Gemma 4 → SillyTavern → Rino Agent Service）
    .\Start-MaidAI.ps1 -Profile full   # 会話 + 音声関連
    .\Start-MaidAI.ps1 -Status
    .\Start-MaidAI.ps1 -Stop
    .\Start-MaidAI.ps1 -RestartSillyTavern
    .\Start-MaidAI.ps1 -Status -Json   # 機械可読な状態（デスクトップウィジェットが使用）
    .\Start-MaidAI.ps1 -Component 'SillyTavern' -Action restart   # 個別の起動 / 停止 / 再起動
    .\Start-MaidAI.ps1 -Component 'SillyTavern' -Action log       # ログファイルのパスを出力（Docker は docker logs を書き出す）

  Docker のサービスは下部の $DockerProjects と $DockerContainers で管理する。
#>
[CmdletBinding()]
param(
    [ValidateSet('chat', 'voice', 'full', 'docker')]
    [string] $Profile = 'chat',
    [switch] $Status,
    [switch] $Stop,
    [switch] $RestartSillyTavern,
    [Alias('Component')]
    [string] $ComponentName,
    [ValidateSet('start', 'stop', 'restart', 'log')]
    [string] $Action,
    [switch] $Json
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

function Import-RinoEnvironment {
    $allowedNames = @(
        'SWITCHBOT_TOKEN', 'SWITCHBOT_SECRET',
        'SWITCHBOT_CO2_DEVICE_ID', 'SWITCHBOT_LIGHT_DEVICE_ID',
        'SWITCHBOT_AIRCON_DEVICE_ID', 'SWITCHBOT_TV_DEVICE_ID',
        'SWITCHBOT_LOCK_DEVICE_ID', 'RINO_AGENT_API_TOKEN', 'RINO_AGENT_AUDIT_KEY',
        'RINO_OBS_HOST', 'RINO_OBS_PORT', 'RINO_OBS_PASSWORD',
        'RINO_COMFYUI_URL', 'RINO_COMFYUI_WORKFLOW_DIR',
        'RINO_WINDOWS_ALLOWED_APPS', 'RINO_WINDOWS_ALLOWED_ROOTS', 'RINO_SCREENSHOT_DIR',
        'RINO_IMAGE_GENERATION_ENABLED', 'RINO_IMAGE_WORKFLOW', 'RINO_IMAGE_PROMPT_NODE', 'RINO_IMAGE_PROMPT_INPUT',
        'RINO_IMAGE_COMFYUI_URL', 'RINO_IMAGE_KOBOLD_URL', 'RINO_IMAGE_COMFYUI_OUTPUT_DIR',
        'RINO_IMAGE_PUBLIC_OUTPUT_DIR', 'RINO_IMAGE_PUBLIC_URL_PREFIX', 'RINO_IMAGE_KOBOLD_PROCESS',
        'RINO_IMAGE_KOBOLD_START', 'RINO_IMAGE_COMFYUI_START',
        'RINO_LIFE_DB_NAME', 'RINO_LIFE_DB_USER', 'RINO_LIFE_DB_PASSWORD',
        'RINO_LIFE_POSTGRES_PORT', 'RINO_LIFE_NATS_USER', 'RINO_LIFE_NATS_PASSWORD',
        'RINO_LIFE_NATS_PORT', 'RINO_LIFE_NATS_MONITOR_PORT', 'RINO_LIFE_API_URL',
        'RINO_LIFE_DATABASE_URL', 'RINO_LIFE_NATS_URL',
        'RINO_PC_MONITOR_PATH', 'RINO_PC_WATCH_SERVICES', 'RINO_SWITCHBOT_POLL_SECONDS'
    )
    $envFiles = @(
        (Join-Path $Root 'rino\home\.env'),
        (Join-Path $Root 'rino_agent\.env'),
        (Join-Path $Root 'infra\.env.life')
    )
    foreach ($envFile in $envFiles) {
        if (-not (Test-Path -LiteralPath $envFile)) { continue }
        foreach ($line in Get-Content -LiteralPath $envFile) {
            $trimmed = $line.Trim()
            if (-not $trimmed) { continue }
            if ($trimmed.StartsWith('#')) { continue }
            $parts = $trimmed.Split('=', 2)
            if ($parts.Count -ne 2) { continue }
            $name = $parts[0]
            $value = $parts[1].Trim()
            if ($allowedNames -notcontains $name) { continue }
            if ([Environment]::GetEnvironmentVariable($name)) { continue }
            if ($value) { Set-Item -Path "Env:$name" -Value $value }
        }
    }
}

function Test-RinoAgentEnvironment {
    $required = @('RINO_AGENT_API_TOKEN')
    $missing = @($required | Where-Object { -not [Environment]::GetEnvironmentVariable($_) })
    if ($missing.Count) {
        throw 'Rino Agent Service: RINO_AGENT_API_TOKEN is missing. Copy rino_agent\.env.example to .env and set a strong random value.'
    }
}

Import-RinoEnvironment

# Compose プロジェクトはここで一元管理する。Rino Life は chat / full / docker
# プロファイルで必ず起動し、Compose の healthcheck が通るまで待機する。
$DockerProjects = @(
    @{ Name = 'Rino Life'; Path = (Join-Path $Root 'infra\compose.life.yaml'); EnvFile = (Join-Path $Root 'infra\.env.life'); Services = @(); Containers = @('rino-life-postgres', 'rino-life-nats') }
)
$DockerContainers = @(
    @{ Name = 'Rino Life PostgreSQL'; Container = 'rino-life-postgres'; Port = 54329; TimeoutSeconds = 30 },
    @{ Name = 'Rino Life NATS'; Container = 'rino-life-nats'; Port = 54222; TimeoutSeconds = 30 },
    @{ Name = 'MemPalace'; Container = 'mempalace'; Port = 8052; TimeoutSeconds = 120 },
    @{ Name = 'SearXNG'; Container = 'searxng'; Port = 8888; TimeoutSeconds = 120 }
)

# Health は稼働中に応答を確認する loopback の URL（応答がなければウィジェットが「応答異常」と表示する）。
# OpenUrl はウィジェットが既定ブラウザで開く loopback の URL。
$Components = @(
    @{ Name = 'KoboldCpp (Gemma 4)'; Port = 5001; TimeoutSeconds = 600; Kind = 'exe'; File = (Join-Path $Root 'koboldcpp\koboldcpp.exe'); Args = @('--config', (Join-Path $Root 'koboldcpp\Gemma4.kcpps')); Health = 'http://127.0.0.1:5001/api/v1/model' },
    @{ Name = 'SillyTavern'; Port = 8000; TimeoutSeconds = 120; Kind = 'cmd'; File = (Join-Path $Root 'SillyTavern\Start.bat'); Args = @(); Health = 'http://127.0.0.1:8000/'; OpenUrl = 'http://127.0.0.1:8000/' },
    @{ Name = 'Rino Agent Service'; Port = 8766; TimeoutSeconds = 30; Kind = 'cmd'; File = (Join-Path $Root 'rino_agent\Start-AgentService.cmd'); Args = @(); Health = 'http://127.0.0.1:8766/health' },
    @{ Name = 'Rino Life API'; Port = 54330; TimeoutSeconds = 30; Kind = 'cmd'; File = (Join-Path $Root 'rino_life\Start-LifeApi.cmd'); Args = @(); Health = 'http://127.0.0.1:54330/health' },
    @{ Name = 'RVC API'; Port = 5050; TimeoutSeconds = 120; Kind = 'cmd'; File = (Join-Path $Root 'rvc-python\Start-RVC.cmd'); Args = @() },
    @{ Name = 'EdgeTTS'; Port = 5100; TimeoutSeconds = 60; Kind = 'cmd'; File = (Join-Path $Root 'SillyTavern-extras\Start-Edge-TTS.cmd'); Args = @() }
)

# プロファイル定義。起動対象と、状態 JSON の profiles 項目（ウィジェットのプロファイル充足表示）の唯一の出所。
# Docker（Compose プロジェクトと DockerContainers 全部）は $DockerProfiles のプロファイルでのみ起動する。
$ProfileComponents = @{
    chat   = @('KoboldCpp (Gemma 4)', 'SillyTavern', 'Rino Life API', 'Rino Agent Service')
    voice  = @('RVC API', 'EdgeTTS')
    full   = @('KoboldCpp (Gemma 4)', 'SillyTavern', 'Rino Life API', 'Rino Agent Service', 'RVC API', 'EdgeTTS')
    docker = @()
}
$DockerProfiles = @('chat', 'full', 'docker')
$LogDir = Join-Path $Root 'logs\services'

function Get-ProfilesOf([string] $Name, [bool] $IsDocker) {
    $result = @()
    foreach ($profileName in @('chat', 'voice', 'full', 'docker')) {
        if ($IsDocker) { if ($DockerProfiles -contains $profileName) { $result += $profileName } }
        elseif ($ProfileComponents[$profileName] -contains $Name) { $result += $profileName }
    }
    return $result
}

function Get-LogPath([string] $Name) {
    $slug = ($Name.ToLowerInvariant() -replace '[^a-z0-9]+', '-').Trim('-')
    return (Join-Path $LogDir "$slug.log")
}

# サービスのログが 5MB を超えていたら .old.log へ退避してから追記を始める。
function Initialize-ServiceLog([string] $Name) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $path = Get-LogPath $Name
    if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -gt 5MB) {
        Move-Item -LiteralPath $path -Destination ($path -replace '\.log$', '.old.log') -Force
    }
    return $path
}

# loopback の HTTP 応答を確認する。2xx/3xx と 401/403（認証付きで稼働中）を正常とみなす。
function Test-HttpHealth([string] $Url) {
    $client = $null
    try {
        Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
        $client = [System.Net.Http.HttpClient]::new()
        $client.Timeout = [TimeSpan]::FromMilliseconds(1500)
        $code = [int] $client.GetAsync($Url).GetAwaiter().GetResult().StatusCode
        return (($code -ge 200 -and $code -lt 400) -or $code -eq 401 -or $code -eq 403)
    } catch {
        return $false
    } finally {
        if ($client) { $client.Dispose() }
    }
}

function Get-PortProcess([int] $Port) {
    if ($Port -le 0) { return $null }
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess
}

function Test-LocalTcpPort([int] $Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $result = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($result)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Wait-ForPort([string] $Name, [int] $Port, [int] $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    Write-Host "Waiting for $Name (port $Port)..." -ForegroundColor DarkCyan
    while ((Get-Date) -lt $deadline) {
        if (Test-LocalTcpPort $Port) {
            Write-Host "${Name}: ready." -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "$Name did not become ready on port $Port within $TimeoutSeconds seconds."
}

# 時刻文字列（Docker の RFC3339 ナノ秒表記を含む）を UTC の ISO 8601 文字列にする。解釈不能・未起動（0001 年）は $null。
function ConvertTo-UtcIso($Value) {
    if ($null -eq $Value) { return $null }
    $text = ([string] $Value).Trim() -replace '(\.\d{7})\d+', '$1'
    $parsed = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse($text, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref] $parsed)) { return $null }
    if ($parsed.Year -lt 2000) { return $null }
    return $parsed.UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ssZ')
}

function Get-ProcessStartedAt([int] $ProcessId) {
    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        return ConvertTo-UtcIso $process.StartTime.ToUniversalTime().ToString('o', [Globalization.CultureInfo]::InvariantCulture)
    } catch {
        return $null
    }
}

# 状態を機械可読なオブジェクトで返す。state は running / loading / stopped / missing / unavailable。
# kind は process（ローカルプロセス）/ container（Docker コンテナ）/ project（Compose プロジェクト）。
# started_at は最終起動時刻（UTC ISO 8601、不明は null）。process は稼働中のリスナー、container は Docker の
# State.StartedAt（停止中でも直近の起動時刻）、project はメンバーコンテナのうち最新の起動時刻。
# health は稼働中の応答確認（ok / fail、確認手段がなければ null）。process は Health URL、container は Docker healthcheck、
# project はメンバーに fail があれば fail。open_url はブラウザで開ける loopback URL（なければ null）。
# profiles はそのコンポーネントを起動するプロファイル名の配列。
function Get-MaidAIStatus {
    $items = @()
    foreach ($component in $Components) {
        $state = 'stopped'
        $listenerPid = $null
        $processName = $null
        $startedAt = $null
        $health = $null
        $loadingProcess = if ($component.Name -eq 'KoboldCpp (Gemma 4)') { Get-Process -Name 'koboldcpp' -ErrorAction SilentlyContinue | Select-Object -First 1 } else { $null }
        if ($loadingProcess -and -not (Get-PortProcess $component.Port)) {
            $state = 'loading'
            $startedAt = Get-ProcessStartedAt $loadingProcess.Id
        } else {
            $listenerPid = Get-PortProcess $component.Port
            if ($listenerPid) {
                $state = 'running'
                $processName = (Get-Process -Id $listenerPid -ErrorAction SilentlyContinue).ProcessName
                $startedAt = Get-ProcessStartedAt $listenerPid
                if ($component.Health) { $health = if (Test-HttpHealth $component.Health) { 'ok' } else { 'fail' } }
            }
        }
        $openUrl = if ($component.OpenUrl) { $component.OpenUrl } else { $null }
        $items += [pscustomobject]@{ name = $component.Name; kind = 'process'; port = $component.Port; state = $state; pid = $listenerPid; process = $processName; started_at = $startedAt; health = $health; open_url = $openUrl; profiles = @(Get-ProfilesOf $component.Name $false) }
    }
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    $containerStates = @{}
    $containerStarts = @{}
    $containerHealth = @{}
    foreach ($container in $DockerContainers) {
        $state = 'unavailable'
        $startedAt = $null
        $health = $null
        if ($docker) {
            $info = Get-DockerContainerInfo $container.Container
            $raw = if ($info) { $info.Status } else { $null }
            $containerStates[$container.Container] = $raw
            if ($info) { $startedAt = $info.StartedAt; $containerStarts[$container.Container] = $startedAt }
            $state = if ($raw -eq 'running') { 'running' } elseif ($raw) { 'stopped' } else { 'missing' }
            if ($state -eq 'running' -and $info) { $health = $info.Health }
            $containerHealth[$container.Container] = $health
        }
        $items += [pscustomobject]@{ name = $container.Name; kind = 'container'; port = $container.Port; state = $state; pid = $null; process = $null; started_at = $startedAt; health = $health; open_url = $null; profiles = @(Get-ProfilesOf $container.Name $true) }
    }
    foreach ($project in $DockerProjects) {
        $state = 'unavailable'
        $startedAt = $null
        $health = $null
        if ($docker) {
            $members = @($project.Containers)
            $running = @($members | Where-Object { $containerStates[$_] -eq 'running' })
            $state = if ($members.Count -and $running.Count -eq $members.Count) { 'running' } elseif ($running.Count) { 'loading' } else { 'stopped' }
            # ISO 8601 UTC 固定書式なので文字列比較で最新を選べる
            $startedAt = @($members | ForEach-Object { $containerStarts[$_] } | Where-Object { $_ } | Sort-Object -Descending | Select-Object -First 1)[0]
            if (@($members | Where-Object { $containerHealth[$_] -eq 'fail' }).Count) { $health = 'fail' }
            elseif ($state -eq 'running' -and @($members | Where-Object { $containerHealth[$_] -eq 'ok' }).Count) { $health = 'ok' }
        }
        $items += [pscustomobject]@{ name = $project.Name; kind = 'project'; port = 0; state = $state; pid = $null; process = $null; started_at = $startedAt; health = $health; open_url = $null; profiles = @(Get-ProfilesOf $project.Name $true) }
    }
    return $items
}

function Show-Status {
    Write-Host "`nMaidAI status" -ForegroundColor Cyan
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    $dockerShown = $false
    foreach ($item in (Get-MaidAIStatus)) {
        if ($item.kind -ne 'process' -and -not $dockerShown) {
            Write-Host ("  Docker CLI           {0}" -f $(if ($docker) { 'available' } else { 'not installed / not in PATH' })) -ForegroundColor $(if ($docker) { 'Green' } else { 'DarkYellow' })
            $dockerShown = $true
        }
        if ($item.kind -eq 'process') {
            switch ($item.state) {
                'loading' { Write-Host ("  {0,-18} LOADING  model is being loaded" -f $item.name) -ForegroundColor Yellow }
                'running' { Write-Host ("  {0,-18} RUNNING  http://127.0.0.1:{1}  (PID {2}: {3})" -f $item.name, $item.port, $item.pid, $item.process) -ForegroundColor Green }
                default { Write-Host ("  {0,-18} stopped  (port {1})" -f $item.name, $item.port) -ForegroundColor DarkGray }
            }
        } elseif ($docker) {
            $color = switch ($item.state) { 'running' { 'Green' } 'loading' { 'Yellow' } 'missing' { 'DarkGray' } default { 'DarkYellow' } }
            $label = if ($item.state -eq 'missing') { 'not found' } else { $item.state }
            Write-Host ("  Docker {0,-11} {1}" -f $item.name, $label) -ForegroundColor $color
        }
    }
}

# status（running 等）と最終起動時刻（UTC, ISO 8601。未起動は $null）を返す。未作成は $null。
function Get-DockerContainerInfo([string] $ContainerName) {
    # コンテナ未作成時の docker の stderr を、$ErrorActionPreference='Stop' 下で例外化させない
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $line = & docker container inspect --format '{{.State.Status}}|{{.State.StartedAt}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' $ContainerName 2>$null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($exitCode -ne 0 -or -not $line) { return $null }
    $parts = ([string]($line | Select-Object -First 1)).Trim().Split('|', 3)
    # Docker の healthcheck: healthy → ok、unhealthy → fail、未定義・starting は $null（判定しない）
    $health = if ($parts.Count -gt 2) { switch ($parts[2]) { 'healthy' { 'ok' } 'unhealthy' { 'fail' } default { $null } } } else { $null }
    return [pscustomobject]@{ Status = $parts[0]; StartedAt = ConvertTo-UtcIso $(if ($parts.Count -gt 1) { $parts[1] } else { $null }); Health = $health }
}

function Get-DockerContainerState([string] $ContainerName) {
    $info = Get-DockerContainerInfo $ContainerName
    if ($info -and $info.Status) { return $info.Status }
    return $null
}

function Start-Component($ComponentConfig) {
    if ($null -eq $ComponentConfig -or [string]::IsNullOrWhiteSpace([string] $ComponentConfig.File)) {
        $componentName = if ($null -eq $ComponentConfig) { '<undefined>' } elseif ($ComponentConfig.Name) { $ComponentConfig.Name } else { '<unnamed>' }
        throw "${componentName}: component configuration is missing its launch file."
    }
    if (-not (Test-Path -LiteralPath $ComponentConfig.File)) {
        Write-Warning "$($ComponentConfig.Name): launch file not found: $($ComponentConfig.File)"
        return
    }
    if ($ComponentConfig.Port -gt 0 -and (Get-PortProcess $ComponentConfig.Port)) {
        Write-Host "$($ComponentConfig.Name): already running (port $($ComponentConfig.Port))." -ForegroundColor Yellow
        return
    }
    if ($ComponentConfig.Name -eq 'KoboldCpp (Gemma 4)' -and (Get-Process -Name 'koboldcpp' -ErrorAction SilentlyContinue)) {
        Write-Host "$($ComponentConfig.Name): a KoboldCpp process is already loading or running." -ForegroundColor Yellow
        return
    }
    Write-Host "Starting $($ComponentConfig.Name)..." -ForegroundColor Cyan
    # 標準出力・標準エラーを logs\services\ へ記録する（ウィジェットの「ログを開く」が参照する）。
    # exe は Start-Process が 1 つのファイルへ統合できないため、標準エラーは <名前>.err.log に分ける。
    $logPath = Initialize-ServiceLog $ComponentConfig.Name
    $timestamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    Add-Content -LiteralPath $logPath -Value "===== $timestamp start: $($ComponentConfig.Name) =====" -Encoding UTF8
    switch ($ComponentConfig.Kind) {
        'exe' { Start-Process -FilePath $ComponentConfig.File -ArgumentList $ComponentConfig.Args -WorkingDirectory (Split-Path $ComponentConfig.File) -WindowStyle Hidden -RedirectStandardOutput $logPath -RedirectStandardError ($logPath -replace '\.log$', '.err.log') }
        'cmd' { Start-Process -FilePath 'cmd.exe' -ArgumentList @('/s', '/c', ('"call "{0}" >> "{1}" 2>&1"' -f $ComponentConfig.File, $logPath)) -WorkingDirectory (Split-Path $ComponentConfig.File) -WindowStyle Hidden }
        'powershell' { Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $ComponentConfig.File)) -WorkingDirectory (Split-Path $ComponentConfig.File) -WindowStyle Hidden }
    }
}

function Start-DockerProjects {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Warning 'Docker CLI is unavailable. Start Docker Desktop before using -Profile docker.'
        return
    }
    foreach ($project in $DockerProjects) {
        if (-not (Test-Path -LiteralPath $project.Path)) { Write-Warning "$($project.Name): Compose file not found"; continue }
        $arguments = @('compose')
        if ($project.EnvFile -and (Test-Path -LiteralPath $project.EnvFile)) { $arguments += @('--env-file', $project.EnvFile) }
        $arguments += @('-f', $project.Path, 'up', '-d', '--wait') + $project.Services
        Write-Host "Starting Docker: $($project.Name)..." -ForegroundColor Cyan
        & docker @arguments
    }
    foreach ($container in $DockerContainers) {
        $state = Get-DockerContainerState $container.Container
        if (-not $state) {
            Write-Warning "$($container.Name): Docker container not found: $($container.Container)"
            continue
        }
        if ($state -eq 'running') {
            Write-Host "Docker $($container.Name): already running." -ForegroundColor Yellow
            Wait-ForPort $container.Name $container.Port $container.TimeoutSeconds
            continue
        }
        Write-Host "Starting Docker: $($container.Name)..." -ForegroundColor Cyan
        & docker start $container.Container
        Wait-ForPort $container.Name $container.Port $container.TimeoutSeconds
    }
}

function Stop-Components {
    for ($index = $Components.Count - 1; $index -ge 0; $index--) {
        $component = $Components[$index]
        if ($component.Port -le 0) { continue }
        $listenerPid = Get-PortProcess $component.Port
        if ($listenerPid) {
            $process = Get-Process -Id $listenerPid -ErrorAction SilentlyContinue
            Write-Host "Stopping $($component.Name) (PID ${listenerPid}: $($process.ProcessName))..." -ForegroundColor Cyan
            Stop-Process -Id $listenerPid -Force
        }
    }
    Stop-DockerProjects
}

function Restart-SillyTavern {
    $sillyTavern = $Components | Where-Object { $_.Name -eq 'SillyTavern' } | Select-Object -First 1
    if (-not $sillyTavern) { throw 'SillyTavern component is not configured.' }

    $listenerPid = Get-PortProcess $sillyTavern.Port
    if ($listenerPid) {
        $process = Get-Process -Id $listenerPid -ErrorAction SilentlyContinue
        Write-Host "Stopping $($sillyTavern.Name) (PID ${listenerPid}: $($process.ProcessName))..." -ForegroundColor Cyan
        Stop-Process -Id $listenerPid -Force
        Start-Sleep -Milliseconds 500
    } else {
        Write-Host "$($sillyTavern.Name): not running; starting it." -ForegroundColor Yellow
    }

    Start-Component -ComponentConfig $sillyTavern
    Wait-ForPort $sillyTavern.Name $sillyTavern.Port $sillyTavern.TimeoutSeconds
}

function Stop-DockerProjects {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) { return }
    foreach ($project in $DockerProjects) {
        if (-not (Test-Path -LiteralPath $project.Path)) { continue }
        Write-Host "Stopping Docker: $($project.Name)..." -ForegroundColor Cyan
        $arguments = @('compose')
        if ($project.EnvFile -and (Test-Path -LiteralPath $project.EnvFile)) { $arguments += @('--env-file', $project.EnvFile) }
        $arguments += @('-f', $project.Path, 'stop')
        & docker @arguments
    }
    for ($index = $DockerContainers.Count - 1; $index -ge 0; $index--) {
        $container = $DockerContainers[$index]
        if ((Get-DockerContainerState $container.Container) -ne 'running') { continue }
        Write-Host "Stopping Docker: $($container.Name)..." -ForegroundColor Cyan
        & docker stop $container.Container
    }
}

function Stop-Component($component) {
    $listenerPid = Get-PortProcess $component.Port
    if (-not $listenerPid) {
        Write-Host "$($component.Name): not running." -ForegroundColor Yellow
        return
    }
    $process = Get-Process -Id $listenerPid -ErrorAction SilentlyContinue
    Write-Host "Stopping $($component.Name) (PID ${listenerPid}: $($process.ProcessName))..." -ForegroundColor Cyan
    Stop-Process -Id $listenerPid -Force
}

function Wait-ForPortClosed([string] $Name, [int] $Port, [int] $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-PortProcess $Port)) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not release port $Port within $TimeoutSeconds seconds."
}

function Get-ComposeArguments($project, [string[]] $Command) {
    $arguments = @('compose')
    if ($project.EnvFile -and (Test-Path -LiteralPath $project.EnvFile)) { $arguments += @('--env-file', $project.EnvFile) }
    return $arguments + @('-f', $project.Path) + $Command
}

# -Component で指定できるのは $Components / $DockerContainers / $DockerProjects に定義された名前だけ。
function Invoke-ComponentAction([string] $Name, [string] $Operation) {
    $process = $Components | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    $container = $DockerContainers | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    $project = $DockerProjects | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not ($process -or $container -or $project)) { throw "Unknown component: $Name" }

    if ($Operation -eq 'log') {
        # 開くべきログファイルのパスを最終行に出力する。Docker は docker logs の末尾を書き出したものを指す。
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
        if ($process) {
            $path = Get-LogPath $process.Name
            if (-not (Test-Path -LiteralPath $path)) { throw "$($process.Name): ログがまだありません（ウィジェット / 起動ハブから起動すると記録されます）。" }
        } else {
            if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is unavailable. Start Docker Desktop first.' }
            $path = Get-LogPath $(if ($container) { $container.Name } else { $project.Name })
            # 名前は許可リスト由来なので cmd.exe 経由のリダイレクトに使ってよい（stderr も統合するため）
            if ($container) {
                if (-not (Get-DockerContainerState $container.Container)) { throw "Docker container not found: $($container.Container)" }
                & cmd.exe /c ('docker logs --tail 2000 {0} > "{1}" 2>&1' -f $container.Container, $path)
            } else {
                $composeArgs = (Get-ComposeArguments $project @('logs', '--no-color', '--tail', '500') | ForEach-Object { '"{0}"' -f $_ }) -join ' '
                & cmd.exe /c ('docker {0} > "{1}" 2>&1' -f $composeArgs, $path)
            }
        }
        Write-Output $path
        return
    }

    if ($process) {
        if ($Operation -in @('stop', 'restart')) {
            Stop-Component $process
            Wait-ForPortClosed $process.Name $process.Port 30
        }
        if ($Operation -in @('start', 'restart')) {
            if ($process.Name -eq 'Rino Agent Service') { Test-RinoAgentEnvironment }
            if ($process.Name -eq 'Rino Life API') { & (Join-Path $Root 'Initialize-RinoLife.ps1') }
            Start-Component -ComponentConfig $process
            Wait-ForPort $process.Name $process.Port $process.TimeoutSeconds
        }
        return
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is unavailable. Start Docker Desktop first.' }
    if ($container) {
        if (-not (Get-DockerContainerState $container.Container)) { throw "Docker container not found: $($container.Container)" }
        if ($Operation -in @('stop', 'restart')) { & docker stop $container.Container; if ($LASTEXITCODE -ne 0) { throw "docker stop failed: $($container.Name)" } }
        if ($Operation -in @('start', 'restart')) {
            & docker start $container.Container
            if ($LASTEXITCODE -ne 0) { throw "docker start failed: $($container.Name)" }
            Wait-ForPort $container.Name $container.Port $container.TimeoutSeconds
        }
        return
    }

    if (-not (Test-Path -LiteralPath $project.Path)) { throw "$($project.Name): Compose file not found" }
    if ($Operation -in @('stop', 'restart')) {
        & docker @(Get-ComposeArguments $project @('stop'))
        if ($LASTEXITCODE -ne 0) { throw "docker compose stop failed: $($project.Name)" }
    }
    if ($Operation -in @('start', 'restart')) {
        & docker @(Get-ComposeArguments $project (@('up', '-d', '--wait') + $project.Services))
        if ($LASTEXITCODE -ne 0) { throw "docker compose up failed: $($project.Name)" }
    }
}

if ($ComponentName -or $Action) {
    if (-not ($ComponentName -and $Action)) { throw '-Component and -Action must be specified together.' }
    Invoke-ComponentAction $ComponentName $Action
    exit 0
}
if ($Status -and $Json) { ConvertTo-Json -InputObject @(Get-MaidAIStatus) -Depth 3; exit 0 }
if ($Status) { Show-Status; exit }
if ($Stop) { Stop-Components; exit }
if ($RestartSillyTavern) { Restart-SillyTavern; exit }

$selectedNames = @($ProfileComponents[$Profile])
$selected = @()
if ($selectedNames.Count) {
    # Hashtable をパイプライン出力で配列化すると値だけに展開される場合があるため、
    # 明示的な List に構成オブジェクトそのものを追加する。
    $selected = [System.Collections.Generic.List[object]]::new()
    foreach ($selectedName in $selectedNames) {
        $matchedComponent = $null
        foreach ($candidate in $Components) {
            if ($candidate['Name'] -eq $selectedName) {
                $matchedComponent = $candidate
                break
            }
        }
        if ($null -eq $matchedComponent) { throw "Component configuration not found: $selectedName" }
        [void] $selected.Add($matchedComponent)
    }
}
if ($selected | Where-Object { $_.Name -eq 'Rino Agent Service' }) { Test-RinoAgentEnvironment }
if ($DockerProfiles -contains $Profile) { Start-DockerProjects }
if ($selected | Where-Object { $_.Name -eq 'Rino Life API' }) {
    & (Join-Path $Root 'Initialize-RinoLife.ps1')
}
foreach ($component in $selected) {
    Start-Component -ComponentConfig $component
    Wait-ForPort $component.Name $component.Port $component.TimeoutSeconds
}
Show-Status
