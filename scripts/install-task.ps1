# Install nightly scheduled task for reddit-digest
$ErrorActionPreference = 'Stop'

$root = Split-Path $PSScriptRoot -Parent
$runScript = Join-Path $root 'scripts\run-digest.ps1'

$taskName = "reddit-digest"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File `"$runScript`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At "21:00"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -User $env:USERNAME `
    -Description "Nightly Reddit Digest pull and LLM classification" `
    -Force | Out-Null

Write-Host "Scheduled task '$taskName' registered successfully (Daily at 21:00, user: $env:USERNAME)."
