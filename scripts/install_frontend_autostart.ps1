[CmdletBinding()]
param(
    [string]$TaskName = "AI_Douyin_Streamlit",
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcher = (Resolve-Path (Join-Path $projectRoot "scripts\run_streamlit_web.py")).Path
$pythonwCandidate = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"

if (-not (Test-Path -LiteralPath $pythonwCandidate -PathType Leaf)) {
    throw "Project Python launcher was not found: $pythonwCandidate"
}

$pythonw = (Resolve-Path $pythonwCandidate).Path
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$quotedLauncher = '"' + $launcher + '"'

$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument $quotedLauncher `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$principal = New-ScheduledTaskPrincipal `
    -UserId $taskUser `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Start the AI Douyin Streamlit dashboard at Windows logon." `
    -Force | Out-Null

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
}

$task = Get-ScheduledTask -TaskName $TaskName
[pscustomobject]@{
    TaskName = $task.TaskName
    State = $task.State
    User = $taskUser
    Python = $pythonw
    Launcher = $launcher
    StartNow = [bool]$StartNow
} | Format-List

