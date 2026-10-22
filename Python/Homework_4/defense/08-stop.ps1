. "$PSScriptRoot\common.ps1"
Assert-Tool -Name 'docker'
Write-Host '=== Stop Docker without deleting the database volume ==='
Invoke-Checked -Executable 'docker' -Arguments @('compose', 'down')
Invoke-Checked -Executable 'docker' -Arguments @('compose', 'ps')
Write-Host 'Docker stopped. The named database volume and local secrets are preserved.'
