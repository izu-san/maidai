[CmdletBinding()]
param([Parameter(Mandatory)][string]$BackupFile)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $BackupFile -PathType Leaf)) { throw 'Backup file was not found' }
# pg_restore --list verifies a custom-format logical backup without touching the
# production database. docker cp avoids PowerShell text conversion of binary dumps.
$compose = Join-Path $PSScriptRoot '..\infra\compose.life.yaml'
$container = docker compose -f $compose ps -q postgres
if (-not $container) { throw 'PostgreSQL container is not running' }
docker cp $BackupFile "${container}:/tmp/rino-life-restore-check.dump"
docker compose -f $compose exec -T postgres pg_restore --list /tmp/rino-life-restore-check.dump | Out-Null
docker compose -f $compose exec -T postgres rm -f /tmp/rino-life-restore-check.dump
if ($LASTEXITCODE -ne 0) { throw 'Backup restore verification failed' }
Write-Output 'Logical restore verification passed.'
