. "$PSScriptRoot\common.ps1"
Assert-Tool -Name 'py'
Require-Secrets
Write-Host '=== Automatic bank demonstration ==='
Write-Host 'This demo logs in as alice without printing the password.'
Write-Host 'It can transfer 0.01 to bob after explicit confirmation.'
Invoke-Checked -Executable 'py' -Arguments @((Join-Path $PSScriptRoot 'demo_client.py'))
