. "$PSScriptRoot\common.ps1"
Assert-Tool -Name 'docker'
Require-Secrets

Write-Host '=== Build and start the Docker server ==='
Invoke-Checked -Executable 'docker' -Arguments @('compose', 'up', '--build', '-d')

$containerId = & docker compose ps -q bank | Select-Object -First 1
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($containerId)) {
    throw 'The bank container could not be found after starting.'
}

$healthy = $false
for ($attempt = 0; $attempt -lt 25; $attempt++) {
    $id = ([string]$containerId).Trim()
    $state = & docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $id
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not inspect Docker container health.'
    }
    $state = ([string]$state).Trim()
    if ($state -eq 'healthy') {
        $healthy = $true
        break
    }
    if ($state -eq 'unhealthy' -or $state -eq 'exited') {
        break
    }
    Start-Sleep -Seconds 2
}

Invoke-Checked -Executable 'docker' -Arguments @('compose', 'ps')
if (-not $healthy) {
    Write-Host 'Recent container logs:'
    & docker compose logs --tail=30 bank
    throw "Server did not reach healthy state (last state: $state)."
}

Write-Host 'Server is healthy. Address: 127.0.0.1:9999'
Write-Host 'Existing database and local secrets were kept.'
