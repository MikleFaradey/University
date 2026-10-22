. "$PSScriptRoot\common.ps1"
$semgrep = Find-Semgrep
$pythonRules = Join-Path $ProjectRoot 'semgrep-rules\python'
$dockerRules = Join-Path $ProjectRoot 'semgrep-rules\dockerfile'
foreach ($folder in @($pythonRules, $dockerRules)) {
    if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
        throw "Missing Semgrep rules: $folder. Clone https://github.com/semgrep/semgrep-rules.git into semgrep-rules."
    }
}

Write-Host '=== Semgrep: Python and Dockerfile ==='
Invoke-Checked -Executable $semgrep -Arguments @('--version')

$outDir = Join-Path $ProjectRoot 'defense-results'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$report = Join-Path $outDir 'semgrep-report.json'

Invoke-Checked -Executable $semgrep -Arguments @(
    'scan', '--metrics=off',
    '--config', $pythonRules,
    '--config', $dockerRules,
    '--json', '--output', $report,
    'main.py', 'bank_client.py', 'setup_demo.py', 'Dockerfile'
)

$data = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
$findings = @($data.results).Count
$errors = @($data.errors).Count
$scanned = @($data.paths.scanned).Count
Write-Host "Files scanned: $scanned"
Write-Host "Findings: $findings"
Write-Host "Scan errors: $errors"
Write-Host "JSON report: $report"
if ($errors -gt 0 -or $scanned -lt 4) {
    throw 'Incomplete scan or errors in the Semgrep JSON report.'
}
Write-Host 'Zero findings does not prove complete security. Verify that rules were loaded.'
