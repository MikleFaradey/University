. "$PSScriptRoot\common.ps1"
Assert-Tool -Name 'py'
Write-Host '=== Unit and security tests ==='
Write-Host 'On Windows, the POSIX file-permission test is expected to be skipped.'
Invoke-Checked -Executable 'py' -Arguments @('-m', 'unittest', '-v', 'test_security')
Write-Host 'All executed tests finished successfully.'
