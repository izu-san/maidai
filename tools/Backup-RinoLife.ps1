[CmdletBinding()]
param(
    [string]$BackupDirectory = (Join-Path $PSScriptRoot "..\backups\life"),
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$required = 'RINO_LIFE_DB_NAME','RINO_LIFE_DB_USER','RINO_LIFE_DB_PASSWORD'
foreach ($name in $required) { if (-not [Environment]::GetEnvironmentVariable($name)) { throw "$name must be set" } }
New-Item -ItemType Directory -Force -Path $BackupDirectory | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dbFile = Join-Path $BackupDirectory "rino-life-$stamp.dump"
if (-not $VerifyOnly) {
    $env:PGPASSWORD = $env:RINO_LIFE_DB_PASSWORD
    $compose = Join-Path $PSScriptRoot '..\infra\compose.life.yaml'
    $container = docker compose -f $compose ps -q postgres
    if (-not $container) { throw 'PostgreSQL container is not running' }
    try {
        docker compose -f $compose exec -T postgres sh -c "pg_dump -U '$env:RINO_LIFE_DB_USER' -d '$env:RINO_LIFE_DB_NAME' -Fc -f /tmp/rino-life.dump"
        docker cp "${container}:/tmp/rino-life.dump" $dbFile
    }
    finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    if ((Get-Item -LiteralPath $dbFile).Length -eq 0) { throw 'Database backup is empty' }
}
# JetStream is backed by the named Docker volume. Archive it through the container,
# never by copying live host files.
$natsFile = Join-Path $BackupDirectory "rino-life-jetstream-$stamp.tgz"
if (-not $VerifyOnly) {
    $natsContainer = docker compose -f $compose ps -q nats
    if (-not $natsContainer) { throw 'NATS container is not running' }
    docker compose -f $compose exec -T nats tar -C /data -czf /tmp/rino-life-jetstream.tgz .
    docker cp "${natsContainer}:/tmp/rino-life-jetstream.tgz" $natsFile
}
Write-Output "Backup completed: $dbFile"
