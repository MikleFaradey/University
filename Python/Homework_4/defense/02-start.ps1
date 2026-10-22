. "$PSScriptRoot\common.ps1"
Assert-Tool -Name 'docker'
Require-Secrets

function Show-DockerDiagnostics {
    Write-Host '=== All bank containers (including stopped) ==='
    & docker compose ps --all
    Write-Host '=== Last 80 bank log lines ==='
    & docker compose logs --no-color --tail=80 bank
}

Write-Host '=== Build and start the Docker server ==='
Invoke-Checked -Executable 'docker' -Arguments @('compose', 'up', '--build', '-d')

# A newly started container might not appear in plain "docker compose ps -q".
# Include stopped/starting containers and allow a brief registration delay.
$containerId = $null
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    $rawIds = & docker compose ps --all --quiet bank
    $psExitCode = $LASTEXITCODE
    if ($psExitCode -ne 0) {
        Show-DockerDiagnostics
        throw "docker compose ps --all --quiet bank failed ($psExitCode)."
    }

    $ids = @($rawIds | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($ids.Count -gt 0) {
        $containerId = ([string]$ids[0]).Trim()
        break
    }
    Start-Sleep -Seconds 1
}

if ([string]::IsNullOrWhiteSpace($containerId)) {
    Show-DockerDiagnostics
    throw 'Bank container is missing, even with --all. Review Compose status and logs above.'
}

# Wait for the asynchronous Docker healthcheck.
$healthy = $false
$state = 'unknown'
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    $rawState = & docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $containerId
    $inspectExitCode = $LASTEXITCODE
    if ($inspectExitCode -ne 0) {
        Show-DockerDiagnostics
        throw "Could not inspect the bank container ($inspectExitCode)."
    }

    $state = ([string]$rawState).Trim()
    if ($state -eq 'healthy') {
        $healthy = $true
        break
    }
    if ($state -eq 'unhealthy' -or $state -eq 'exited' -or $state -eq 'dead') {
        break
    }
    Start-Sleep -Seconds 2
}

Write-Host '=== Docker status ==='
Invoke-Checked -Executable 'docker' -Arguments @('compose', 'ps', '--all')

if (-not $healthy) {
    Show-DockerDiagnostics
    throw "Server did not reach healthy state (last state: $state)."
}

Write-Host 'Server is healthy. Address: 127.0.0.1:9999'
Write-Host 'Periodic "TLS connection rejected" messages can come from the TCP-only Docker healthcheck.'
Write-Host 'Existing database and local secrets were kept.'
