<#
  MaidAI の起動ハブ
  例:
    .\Start-MaidAI.ps1                 # 会話用（Gemma 4 → SillyTavern → Rino Agent Service）
    .\Start-MaidAI.ps1 -Profile full   # 会話 + 音声関連
    .\Start-MaidAI.ps1 -Status
    .\Start-MaidAI.ps1 -Stop
    .\Start-MaidAI.ps1 -RestartSillyTavern

  Docker のサービスは下部の $DockerProjects と $DockerContainers で管理する。
#>
[CmdletBinding()]
param(
    [ValidateSet('chat', 'voice', 'full', 'docker')]
    [string] $Profile = 'chat',
    [switch] $Status,
    [switch] $Stop,
    [switch] $RestartSillyTavern
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
        'RINO_IMAGE_KOBOLD_START', 'RINO_IMAGE_COMFYUI_START'
        ,'RINO_LIFE_DB_NAME', 'RINO_LIFE_DB_USER', 'RINO_LIFE_DB_PASSWORD',
        'RINO_LIFE_POSTGRES_PORT', 'RINO_LIFE_NATS_USER', 'RINO_LIFE_NATS_PASSWORD',
        'RINO_LIFE_NATS_PORT', 'RINO_LIFE_NATS_MONITOR_PORT', 'RINO_LIFE_API_URL',
        'RINO_LIFE_DATABASE_URL', 'RINO_LIFE_NATS_URL'
    )
    $envFiles = @(
        (Join-Path $Root 'rino\home\.env'),
        (Join-Path $Root 'rino_agent\.env')
        ,(Join-Path $Root 'infra\.env.life')
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

# Compose 起動は既定では行わない。必要になった場合だけここに登録する。
# 例: @{ Name = 'search'; Path = 'D:\AI\my-search\compose.yaml'; Services = @() }
$DockerProjects = @(
    @{ Name = 'Rino Life'; Path = (Join-Path $Root 'infra\compose.life.yaml'); EnvFile = (Join-Path $Root 'infra\.env.life'); Services = @() }
)
$DockerContainers = @(
    @{ Name = 'MemPalace'; Container = 'mempalace'; Port = 8052; TimeoutSeconds = 120 },
    @{ Name = 'SearXNG'; Container = 'searxng'; Port = 8888; TimeoutSeconds = 120 }
)

$Components = @(
    @{ Name = 'KoboldCpp (Gemma 4)'; Port = 5001; TimeoutSeconds = 600; Kind = 'exe'; File = (Join-Path $Root 'koboldcpp\koboldcpp.exe'); Args = @('--config', (Join-Path $Root 'koboldcpp\Gemma4.kcpps')) },
    @{ Name = 'SillyTavern'; Port = 8000; TimeoutSeconds = 120; Kind = 'cmd'; File = (Join-Path $Root 'SillyTavern\Start.bat'); Args = @() },
    @{ Name = 'Rino Agent Service'; Port = 8766; TimeoutSeconds = 30; Kind = 'cmd'; File = (Join-Path $Root 'rino_agent\Start-AgentService.cmd'); Args = @() },
    @{ Name = 'Rino Life API'; Port = 54330; TimeoutSeconds = 30; Kind = 'cmd'; File = (Join-Path $Root 'rino_life\Start-LifeApi.cmd'); Args = @() },
    @{ Name = 'RVC API'; Port = 5050; TimeoutSeconds = 120; Kind = 'cmd'; File = (Join-Path $Root 'rvc-python\Start-RVC.cmd'); Args = @() },
    @{ Name = 'EdgeTTS'; Port = 5100; TimeoutSeconds = 60; Kind = 'cmd'; File = (Join-Path $Root 'SillyTavern-extras\Start-Edge-TTS.cmd'); Args = @() }
)

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

function Show-Status {
    Write-Host "`nMaidAI status" -ForegroundColor Cyan
    foreach ($component in $Components) {
        if ($component.Port -le 0) {
            Write-Host ("  {0,-18} port auto-detected / check its console" -f $component.Name) -ForegroundColor DarkYellow
            continue
        }
        if ($component.Name -eq 'KoboldCpp (Gemma 4)' -and (Get-Process -Name 'koboldcpp' -ErrorAction SilentlyContinue) -and -not (Get-PortProcess $component.Port)) {
            Write-Host ("  {0,-18} LOADING  model is being loaded" -f $component.Name) -ForegroundColor Yellow
            continue
        }
        $listenerPid = Get-PortProcess $component.Port
        if ($listenerPid) {
            $process = Get-Process -Id $listenerPid -ErrorAction SilentlyContinue
            Write-Host ("  {0,-18} RUNNING  http://127.0.0.1:{1}  (PID {2}: {3})" -f $component.Name, $component.Port, $listenerPid, $process.ProcessName) -ForegroundColor Green
        } else {
            Write-Host ("  {0,-18} stopped  (port {1})" -f $component.Name, $component.Port) -ForegroundColor DarkGray
        }
    }
    if ($DockerProjects.Count -or $DockerContainers.Count) {
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        Write-Host ("  Docker CLI           {0}" -f $(if ($docker) { 'available' } else { 'not installed / not in PATH' })) -ForegroundColor $(if ($docker) { 'Green' } else { 'DarkYellow' })
        if ($docker) {
            foreach ($container in $DockerContainers) {
                $state = Get-DockerContainerState $container.Container
                $color = if ($state -eq 'running') { 'Green' } elseif ($state) { 'DarkYellow' } else { 'DarkGray' }
                $label = if ($state) { $state } else { 'not found' }
                Write-Host ("  Docker {0,-11} {1}" -f $container.Name, $label) -ForegroundColor $color
            }
        }
    }
}

function Get-DockerContainerState([string] $ContainerName) {
    $state = & docker container inspect --format '{{.State.Status}}' $ContainerName 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return $state.Trim()
}

function Start-Component($component) {
    if (-not (Test-Path -LiteralPath $component.File)) {
        Write-Warning "$($component.Name): launch file not found: $($component.File)"
        return
    }
    if ($component.Port -gt 0 -and (Get-PortProcess $component.Port)) {
        Write-Host "$($component.Name): already running (port $($component.Port))." -ForegroundColor Yellow
        return
    }
    if ($component.Name -eq 'KoboldCpp (Gemma 4)' -and (Get-Process -Name 'koboldcpp' -ErrorAction SilentlyContinue)) {
        Write-Host "$($component.Name): a KoboldCpp process is already loading or running." -ForegroundColor Yellow
        return
    }
    Write-Host "Starting $($component.Name)..." -ForegroundColor Cyan
    switch ($component.Kind) {
        'exe' { Start-Process -FilePath $component.File -ArgumentList $component.Args -WorkingDirectory (Split-Path $component.File) -WindowStyle Hidden }
        'cmd' { Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', 'call', ('"{0}"' -f $component.File)) -WorkingDirectory (Split-Path $component.File) -WindowStyle Hidden }
        'powershell' { Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $component.File)) -WorkingDirectory (Split-Path $component.File) -WindowStyle Hidden }
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
        $arguments += @('-f', $project.Path, 'up', '-d') + $project.Services
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

    Start-Component $sillyTavern
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
        $arguments += @('-f', $project.Path, 'down')
        & docker @arguments
    }
    for ($index = $DockerContainers.Count - 1; $index -ge 0; $index--) {
        $container = $DockerContainers[$index]
        if ((Get-DockerContainerState $container.Container) -ne 'running') { continue }
        Write-Host "Stopping Docker: $($container.Name)..." -ForegroundColor Cyan
        & docker stop $container.Container
    }
}

if ($Status) { Show-Status; exit }
if ($Stop) { Stop-Components; exit }
if ($RestartSillyTavern) { Restart-SillyTavern; exit }

switch ($Profile) {
    'chat' { $selected = @($Components[0], $Components[1], $Components[3], $Components[2]) }
    'voice' { $selected = @($Components[3], $Components[4]) }
    'full' { $selected = $Components }
    'docker' { $selected = @() }
}
if ($selected | Where-Object { $_.Name -eq 'Rino Agent Service' }) { Test-RinoAgentEnvironment }
if ($Profile -in @('chat', 'full', 'docker')) { Start-DockerProjects }
foreach ($component in $selected) {
    Start-Component $component
    Wait-ForPort $component.Name $component.Port $component.TimeoutSeconds
}
Show-Status
