[CmdletBinding()]
param(
    [string]$TaskName = "AI_Douyin_Streamlit"
)

$ErrorActionPreference = "Stop"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Output "Scheduled task does not exist: $TaskName"
    exit 0
}

if ($task.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "Removed scheduled task: $TaskName"

