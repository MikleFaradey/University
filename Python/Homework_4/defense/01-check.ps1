. "$PSScriptRoot\common.ps1"
Write-Host '=== Homework 4: environment ==='
Write-Host "Project: $ProjectRoot"

Assert-Tool -Name 'py'
Invoke-Checked -Executable 'py' -Arguments @('--version')

Assert-Tool -Name 'docker'
Invoke-Checked -Executable 'docker' -Arguments @('--version')
Invoke-Checked -Executable 'docker' -Arguments @('compose', 'version')

& docker info --format '{{.ServerVersion}}' | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Docker Engine is unavailable. Start Docker Desktop before stage 2.'
} else {
    Write-Host 'Docker Engine is available.'
}

foreach ($name in @('users.json', 'server.crt', 'server.key')) {
    $path = Join-Path $ProjectRoot ("secrets\" + $name)
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Write-Host "secrets/$name : present (content is not printed)"
    } else {
        Write-Warning "secrets/$name : missing"
    }
}

foreach ($name in @('python', 'dockerfile')) {
    $path = Join-Path $ProjectRoot ("semgrep-rules\" + $name)
    if (Test-Path -LiteralPath $path -PathType Container) {
        Write-Host "semgrep-rules/$name : present"
    } else {
        Write-Warning "semgrep-rules/$name : missing. Clone semgrep-rules before stage 6."
    }
}

try {
    $semgrep = Find-Semgrep
    Write-Host "Semgrep executable: $semgrep"
    Invoke-Checked -Executable $semgrep -Arguments @('--version')
} catch {
    Write-Warning $_.Exception.Message
}

Write-Host 'Environment check complete.'
