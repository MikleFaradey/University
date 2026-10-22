. "$PSScriptRoot\common.ps1"
Assert-Tool -Name 'py'
Require-Secrets
Write-Host '=== Interactive TLS bank client ==='
Write-Host 'Login: alice. Password is in local secrets/users.json; do not display it.'
Write-Host 'Use QUIT to return to the defense menu.'
Invoke-Checked -Executable 'py' -Arguments @('bank_client.py')
