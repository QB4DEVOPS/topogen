# TG-165 closeout pipeline — offline gates (Stage 1 + Stage 2)
# Exit 0 = pass; non-zero = fail (CI-friendly)
# Usage: .\scripts\validate-tg165.ps1 [-RepoRoot <path>] [-ArtifactRoot <path>] [-SkipPytest]

param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$ArtifactRoot = "C:\tfval\tg165_pki_staging\offline",
    [switch]$SkipPytest
)

$ErrorActionPreference = "Stop"
$failed = 0

function Write-Gate {
    param([string]$Name, [bool]$Pass, [string]$Detail = "")
    $icon = if ($Pass) { "PASS" } else { "FAIL"; $script:failed++ }
    Write-Host "[$icon] $Name" -ForegroundColor $(if ($Pass) { "Green" } else { "Red" })
    if ($Detail) { Write-Host "       $Detail" }
}

Set-Location $RepoRoot

# --- Stage 1: unit tests ---
if (-not $SkipPytest) {
    Write-Host "`n=== Stage 1: Unit tests ===" -ForegroundColor Cyan
    $pytestOut = python -m pytest tests/test_staging_pki.py -q 2>&1 | Out-String
    $pytestPass = ($LASTEXITCODE -eq 0) -and ($pytestOut -match "8 passed")
    Write-Gate "pytest tests/test_staging_pki.py" $pytestPass $pytestOut.Trim()
} else {
    Write-Host "`n=== Stage 1: skipped (-SkipPytest) ===" -ForegroundColor Yellow
}

# --- Stage 2: offline YAML contract ---
Write-Host "`n=== Stage 2: Offline YAML contract ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $ArtifactRoot | Out-Null

$baseArgs = @(
    "-m", "topogen", "3",
    "-m", "dmvpn",
    "--dmvpn-hubs", "1",
    "--device-template", "csr1000v",
    "--overwrite"
)

function Invoke-Topogen {
    param([string[]]$ExtraArgs)
    $all = $baseArgs + $ExtraArgs
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & python @all 1>$null 2>$null
    $exit = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return $exit
}

$stagedYaml = Join-Path $ArtifactRoot "pki-staged.yaml"
$noStagingYaml = Join-Path $ArtifactRoot "pki-no-staging.yaml"
$oldSchemaYaml = Join-Path $ArtifactRoot "pki-old-schema.yaml"

$rcA = Invoke-Topogen @(
    "--pki", "--cml-version", "0.3.1",
    "--offline-yaml", $stagedYaml
)
Write-Gate "generate case A (--pki --cml-version 0.3.1)" ($rcA -eq 0)

if (Test-Path $stagedYaml) {
    $a = Get-Content $stagedYaml -Raw
    Write-Gate "case A: node_staging present" ($a -match "node_staging:")
    Write-Gate "case A: enabled: true" ($a -match "enabled:\s*true")
    Write-Gate "case A: CA-ROOT label" ($a -match "label:\s*CA-ROOT")
    Write-Gate "case A: priority 900" ($a -match "priority:\s*900")
} else {
    Write-Gate "case A: file exists" $false $stagedYaml
}

$rcB = Invoke-Topogen @(
    "--pki", "--no-staging", "--cml-version", "0.3.1",
    "--offline-yaml", $noStagingYaml
)
Write-Gate "generate case B (--no-staging)" ($rcB -eq 0)

if (Test-Path $noStagingYaml) {
    $b = Get-Content $noStagingYaml -Raw
    Write-Gate "case B: no node_staging" (-not ($b -match "node_staging:"))
} else {
    Write-Gate "case B: file exists" $false $noStagingYaml
}

$rcC = Invoke-Topogen @(
    "--pki", "--cml-version", "0.3.0",
    "--offline-yaml", $oldSchemaYaml
)
Write-Gate "generate case C (--cml-version 0.3.0)" ($rcC -eq 0)

if (Test-Path $oldSchemaYaml) {
    $c = Get-Content $oldSchemaYaml -Raw
    Write-Gate "case C: no node_staging (CML 2.8/2.9 schema)" (-not ($c -match "node_staging:"))
} else {
    Write-Gate "case C: file exists" $false $oldSchemaYaml
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
if ($failed -eq 0) {
    Write-Host "All offline gates PASSED. Stage 3 (live CML 2.10) still required before Jira Done." -ForegroundColor Green
    Write-Host "See docs/validation/TG-165-pipeline.md"
    exit 0
} else {
    Write-Host "$failed gate(s) FAILED." -ForegroundColor Red
    exit 1
}
