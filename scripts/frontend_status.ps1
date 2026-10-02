[CmdletBinding()]
param(
    [string]$TaskName = "AI_Douyin_Streamlit",
    [string]$HealthUrl = "http://127.0.0.1:8501/_stcore/health"
)

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskInfo = if ($null -ne $task) {
    Get-ScheduledTaskInfo -TaskName $TaskName
} else {
    $null
}

$health = "unreachable"
try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
        $health = $response.Content.Trim()
    }
} catch {
    $health = "unreachable"
}

[pscustomobject]@{
    TaskInstalled = $null -ne $task
    TaskState = if ($null -ne $task) { [string]$task.State } else { "missing" }
    LastRunTime = if ($null -ne $taskInfo) { $taskInfo.LastRunTime } else { $null }
    LastTaskResult = if ($null -ne $taskInfo) { $taskInfo.LastTaskResult } else { $null }
    HealthUrl = $HealthUrl
    Health = $health
} | Format-List

