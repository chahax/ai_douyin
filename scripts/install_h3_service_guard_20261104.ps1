param([string]$ConfigPath = (Join-Path $PSScriptRoot '..\data\h3_supervision\service_8190_20261104\SERVICE_PLAN.json'))
$ErrorActionPreference = 'Stop'
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$homeDir = Split-Path -Parent $ConfigPath
$review = Get-Content -LiteralPath (Join-Path $homeDir 'PRIMARY_REVIEW.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($review.approved -ne $true -or $review.config_sha256 -ne (Get-FileHash -LiteralPath $ConfigPath).Hash) { throw 'Explicit matching primary review required' }
foreach ($binding in $config.bindings) {
    if ((Get-FileHash -LiteralPath $binding.path).Hash -ne $binding.sha256) { throw "Changed binding $($binding.path)" }
}
$taskName = $config.task_name
$target = Join-Path $homeDir 'TASK.xml'
$taskDocument = Get-Content -LiteralPath $target -Raw -Encoding UTF8
[xml]$expected = $taskDocument
function Resolve-UserSid($name) {
    if ($name -match '^S-1-') { return $name }
    return ([System.Security.Principal.NTAccount]::new($name)).Translate([System.Security.Principal.SecurityIdentifier]).Value
}
function Assert-TaskIdentity($registered) {
    [xml]$doc = $registered.Xml
    $actual = $doc.Task
    $wanted = $expected.Task
    if (@($actual.Actions.ChildNodes).Count -ne 1 -or $actual.Actions.Exec.Command -ne $wanted.Actions.Exec.Command -or
        $actual.Actions.Exec.Arguments -ne $wanted.Actions.Exec.Arguments -or $actual.Actions.Exec.WorkingDirectory -ne $wanted.Actions.Exec.WorkingDirectory -or
        (Resolve-UserSid $actual.Principals.Principal.UserId) -ne (Resolve-UserSid $wanted.Principals.Principal.UserId) -or
        $actual.Principals.Principal.LogonType -ne 'InteractiveToken' -or $actual.Principals.Principal.RunLevel -eq 'HighestAvailable' -or
        @($actual.Triggers.ChildNodes).Count -ne 2 -or $null -eq $actual.Triggers.LogonTrigger -or
        (Resolve-UserSid $actual.Triggers.LogonTrigger.UserId) -ne (Resolve-UserSid $wanted.Triggers.LogonTrigger.UserId) -or
        $actual.Triggers.TimeTrigger.Repetition.Interval -ne 'PT1M' -or $actual.Settings.ExecutionTimeLimit -ne 'PT0S' -or
        $actual.Settings.MultipleInstancesPolicy -ne 'IgnoreNew' -or $actual.Settings.Hidden -ne 'true' -or
        $actual.Settings.Enabled -eq 'false' -or $actual.Triggers.TimeTrigger.Enabled -eq 'false' -or $actual.Triggers.LogonTrigger.Enabled -eq 'false') {
        throw 'Conflicting task identity/settings. No update performed.'
    }
}
$scheduler = New-Object -ComObject 'Schedule.Service'
$scheduler.Connect()
$folder = $scheduler.GetFolder('\')
$existing = $null
try { $existing = $folder.GetTask($taskName) }
catch {
    $failure = $_.Exception.GetBaseException()
    if ($failure.HResult -ne -2147024894) { throw }
}
if ($null -ne $existing) { Assert-TaskIdentity $existing }
else {
    # TASK_CREATE only; a racing registration cannot be overwritten. XML has no encoding declaration.
    $null = $folder.RegisterTask($taskName, $taskDocument, 2, $config.user, $null, 3, $null)
}
$after = $folder.GetTask($taskName)
Assert-TaskIdentity $after
@{verified_at=(Get-Date).ToString('o'); task=$after.Path; owner=$config.user; command=$expected.Task.Actions.Exec.Command;
  arguments=$expected.Task.Actions.Exec.Arguments; config_sha256=$review.config_sha256} | ConvertTo-Json |
  Set-Content -LiteralPath (Join-Path $homeDir 'TASK_DEPLOYMENT_VERIFIED.json') -Encoding UTF8
