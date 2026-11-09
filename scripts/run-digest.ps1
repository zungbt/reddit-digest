# Run daily reddit-digest pipeline and append output to work/log.txt
$ErrorActionPreference = 'Continue'

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$work = Join-Path $root 'work'
if (-not (Test-Path $work)) {
    New-Item -ItemType Directory -Force $work | Out-Null
}
$log = Join-Path $work 'log.txt'

$startTime = Get-Date -Format s
Add-Content $log "`n=== [run-digest start] $startTime ===" -Encoding utf8

& python -m digest run *>> $log
$rc = $LASTEXITCODE

$endTime = Get-Date -Format s
Add-Content $log "=== [run-digest end] $endTime (exit code: $rc) ===`n" -Encoding utf8

exit $rc
