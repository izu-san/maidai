<# Initialize the local Rino Life database and JetStream resources safely. #>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$envFile = Join-Path $Root 'infra\.env.life'

if (-not (Test-Path -LiteralPath $envFile)) {
    throw 'infra\.env.life is missing. Copy infra\.env.life.example and set distinct strong passwords.'
}

$required = @(
    'RINO_LIFE_DB_NAME', 'RINO_LIFE_DB_USER', 'RINO_LIFE_DB_PASSWORD', 'RINO_LIFE_POSTGRES_PORT',
    'RINO_LIFE_NATS_USER', 'RINO_LIFE_NATS_PASSWORD', 'RINO_LIFE_NATS_PORT'
)
foreach ($line in Get-Content -LiteralPath $envFile) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
    $parts = $trimmed.Split('=', 2)
    if ($parts.Count -eq 2 -and $required -contains $parts[0] -and -not [Environment]::GetEnvironmentVariable($parts[0])) {
        Set-Item -Path "Env:$($parts[0])" -Value $parts[1].Trim()
    }
}
$missing = @($required | Where-Object { -not [Environment]::GetEnvironmentVariable($_) })
if ($missing) { throw "infra\.env.life is missing required settings: $($missing -join ', ')" }

# Explicit URLs remain overridable; generated credentials are URI-escaped for psycopg/nats.
if (-not $env:RINO_LIFE_DATABASE_URL) {
    $dbUser = [uri]::EscapeDataString($env:RINO_LIFE_DB_USER)
    $dbPassword = [uri]::EscapeDataString($env:RINO_LIFE_DB_PASSWORD)
    $dbName = [uri]::EscapeDataString($env:RINO_LIFE_DB_NAME)
    # Rino Life passes this value directly to psycopg.  Alembic translates
    # the standard PostgreSQL URL to its SQLAlchemy psycopg dialect internally.
    $env:RINO_LIFE_DATABASE_URL = "postgresql://${dbUser}:${dbPassword}@127.0.0.1:$($env:RINO_LIFE_POSTGRES_PORT)/${dbName}"
}
if (-not $env:RINO_LIFE_NATS_URL) {
    $natsUser = [uri]::EscapeDataString($env:RINO_LIFE_NATS_USER)
    $natsPassword = [uri]::EscapeDataString($env:RINO_LIFE_NATS_PASSWORD)
    $env:RINO_LIFE_NATS_URL = "nats://${natsUser}:${natsPassword}@127.0.0.1:$($env:RINO_LIFE_NATS_PORT)"
}

Push-Location $Root
try {
    $pythonExe = (& py -3.13 -c 'import sys; print(sys.executable)').Trim()
    if (-not $pythonExe) { throw 'Python 3.13 is unavailable.' }
    $alembicExe = Join-Path (Join-Path (Split-Path $pythonExe) 'Scripts') 'alembic.exe'
    if (-not (Test-Path -LiteralPath $alembicExe)) {
        throw 'Rino Life dependencies are missing. Run: py -3.13 -m pip install -r requirements-rino-agent.txt'
    }
    & $alembicExe upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Rino Life database migration failed.' }
    & py -3.13 -c 'from rino_life.consumables import ConsumableService; ConsumableService().seed()'
    if ($LASTEXITCODE -ne 0) { throw 'Rino Life consumable seed failed.' }
    & py -3.13 -m rino_life.nats_setup
    if ($LASTEXITCODE -ne 0) { throw 'Rino Life JetStream setup failed.' }
} finally {
    Pop-Location
}
