<# Create the local Agent Service secret without printing it. #>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$directory = Join-Path $root 'rino_agent'
$path = Join-Path $directory '.env'
if (Test-Path -LiteralPath $path) { throw 'rino_agent\.env already exists; refusing to overwrite it.' }

$bytes = [byte[]]::new(48)
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
[System.IO.File]::WriteAllText($path, "RINO_AGENT_API_TOKEN=$token`r`n", [System.Text.UTF8Encoding]::new($false))
$user = [Environment]::UserName
& icacls $path /inheritance:r /grant:r "${user}:F" 'SYSTEM:F' | Out-Null
if ($LASTEXITCODE -ne 0) { Remove-Item -LiteralPath $path -Force; throw 'Could not restrict rino_agent\.env ACL.' }
Write-Host 'Created rino_agent\.env with a private local API token.' -ForegroundColor Green
