param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$taskName = 'AI_Douyin_Streamlit'
$task = Get-ScheduledTask -TaskName $taskName
$expectedExe = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$expectedScript = Join-Path $projectRoot 'scripts\run_streamlit_web.py'
if ($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ine $expectedExe -or
    $task.Actions[0].Arguments.Trim('"') -ine $expectedScript -or
    $task.Principal.LogonType -ne 'Interactive' -or $task.Settings.MultipleInstances -ne 'IgnoreNew') {
    throw 'Original task identity/settings differ; no scheduled task was changed.'
}
$periodic = @($task.Triggers | Where-Object { $_.Repetition.Interval -eq 'PT5M' })
if (-not $Apply) {
    [pscustomobject]@{task=$taskName; mode='preview'; alreadyConfigured=($periodic.Count -gt 0);
        action=$task.Actions[0].Execute; interval='PT5M'; existingInstances='IgnoreNew';
        maintenance='Disable this task during intentional extended maintenance; enable afterwards.'} | ConvertTo-Json
    exit 0
}
$evidenceDir = Join-Path $projectRoot 'data\account_reboot_repair\20261022'
New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
$beforePath = Join-Path $evidenceDir 'scheduled_task_before_catchup.xml'
if ($periodic.Count -eq 0) {
    if (Test-Path -LiteralPath $beforePath) { throw 'An earlier apply attempt exists; inspect it before repeating.' }
    Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath $beforePath -Encoding utf8
    $newTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5)
    Set-ScheduledTask -TaskName $taskName -Trigger (@($task.Triggers) + @($newTrigger)) | Out-Null
}
$actual = Get-ScheduledTask -TaskName $taskName
if (@($actual.Triggers | Where-Object { $_.Repetition.Interval -eq 'PT5M' }).Count -ne 1 -or
    $actual.Settings.MultipleInstances -ne 'IgnoreNew' -or
    $actual.Actions[0].Execute -ine $expectedExe -or $actual.Actions[0].Arguments.Trim('"') -ine $expectedScript) {
    throw 'Task readback did not match; retain original XML for inspection.'
}
Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $evidenceDir 'scheduled_task_after_catchup.xml') -Encoding utf8
[pscustomobject]@{task=$taskName; mode='applied'; interval='PT5M'; state=[string]$actual.State;
    nextRun=(Get-ScheduledTaskInfo -TaskName $taskName).NextRunTime.ToString('o')} | ConvertTo-Json
