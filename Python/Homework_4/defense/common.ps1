Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $ProjectRoot

function Assert-Tool {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command -Name $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$Arguments = @()
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE"
    }
}

function Find-Semgrep {
    $command = Get-Command -Name semgrep -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    Assert-Tool -Name 'py'
    $scriptsDir = & py -c 'import sysconfig; print(sysconfig.get_path("scripts"))'
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($scriptsDir)) {
        throw 'Could not determine the Python Scripts directory.'
    }

    $scriptsDir = ([string]$scriptsDir).Trim()
    $exe = Join-Path -Path $scriptsDir -ChildPath 'semgrep.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw 'Semgrep executable not found. Install with: py -m pip install semgrep'
    }
    return $exe
}

function Require-Secrets {
    foreach ($name in @('users.json', 'server.crt', 'server.key')) {
        $path = Join-Path $ProjectRoot ("secrets\" + $name)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Missing secrets/$name. Create local secrets once using py setup_demo.py; never commit them."
        }
    }
}
