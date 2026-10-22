. "$PSScriptRoot\common.ps1"
Assert-Tool -Name 'docker'
Write-Host '=== Docker container status and recent logs ==='
$outDir = Join-Path $ProjectRoot 'defense-results'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$status = & docker compose ps
$statusCode = $LASTEXITCODE
$status | Out-Host
if ($statusCode -ne 0) { throw "docker compose ps failed ($statusCode)." }
$status | Out-File -FilePath (Join-Path $outDir 'docker-status.txt') -Encoding UTF8

$logs = & docker compose logs --tail=100 bank
$logsCode = $LASTEXITCODE
$logs | Out-Host
if ($logsCode -ne 0) { throw "docker compose logs failed ($logsCode)." }
$logs | Out-File -FilePath (Join-Path $outDir 'docker-logs.txt') -Encoding UTF8

Write-Host "Status and logs saved under $outDir"
