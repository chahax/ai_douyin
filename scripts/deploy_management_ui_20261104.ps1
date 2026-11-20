param([Parameter(Mandatory=$true)][int]$ExpectedBackendPid)
$ErrorActionPreference = 'Stop'
$rootPath = 'D:\IT\ai_douyin'
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$auditPath = Join-Path $rootPath 'data\development_checkpoints\management_ui_audit_20261104'
$wheelPath = Join-Path $rootPath 'data\qa\management_dependency_20261104\sentence_transformers-5.7.0-py3-none-any.whl'
$taskName = 'AI_Douyin_Streamlit'
$receipt = [ordered]@{ started_at = (Get-Date).ToString('o'); stage = 'preflight'; expected_backend_pid = $ExpectedBackendPid; account_resume_requested = $false; h3_touched = $false }
Set-Location -LiteralPath $rootPath
try {
    $manifest = Get-Content -LiteralPath (Join-Path $auditPath 'SOURCE_MANIFEST.json') -Raw | ConvertFrom-Json
    foreach ($entry in (@($manifest.files) + @($manifest.test_files) + @($manifest.test_reports))) {
        $sourcePath = Join-Path $rootPath $entry.file
        if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
            throw 'Reviewed source changed; revalidation is required before deployment.'
        }
    }
    $progress = Get-Content -LiteralPath (Join-Path $auditPath 'PROGRESS.json') -Raw | ConvertFrom-Json
    $reviewedWheel = @($progress.dependency_wheels | Where-Object file -EQ 'sentence_transformers-5.7.0-py3-none-any.whl')
    if ($reviewedWheel.Count -ne 1 -or (Get-FileHash -LiteralPath $wheelPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $reviewedWheel[0].sha256) {
        throw 'Validated dependency wheel changed.'
    }
    $smoke = Get-Content -LiteralPath (Join-Path $rootPath 'data\qa\management_dependency_20261104\SMOKE_RESULT.json') -Raw | ConvertFrom-Json
    if ($smoke.status -ne 'passed' -or -not $smoke.idempotent_record_count -or -not $smoke.retrieved_synthetic_source) {
        throw 'Isolated dependency acceptance is incomplete.'
    }
    $task = Get-ScheduledTask -TaskName $taskName
    if ($task.State -ne 'Running' -or $task.Principal.LogonType -ne 'Interactive' -or
        $task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne (Join-Path $rootPath '.venv\Scripts\pythonw.exe') -or
        $task.Actions[0].Arguments -ne ('"' + (Join-Path $rootPath 'scripts\run_streamlit_web.py') + '"')) {
        throw 'The registered interactive task does not match the reviewed entry point.'
    }
    & $pythonPath scripts/management_ui_acceptance_snapshot_20261104.py
    if ($LASTEXITCODE -ne 0) { throw 'Original manual read-only proof failed.' }
    & $pythonPath scripts/management_ui_deploy_preflight_20261104.py
    if ($LASTEXITCODE -ne 0) { throw 'Backend is not at the reviewed idle boundary.' }
    $before = Get-Content -LiteralPath (Join-Path $auditPath 'DEPLOY_PREFLIGHT.json') -Raw | ConvertFrom-Json
    if (-not $before.ready -or $before.backend_pid -ne $ExpectedBackendPid) { throw 'Backend identity changed.' }
    $receipt.task_xml_sha256 = (Export-ScheduledTask -TaskName $taskName | ForEach-Object {
        $bytes = [Text.Encoding]::UTF8.GetBytes($_)
        [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
    })
    $receipt.wheel_sha256 = (Get-FileHash -LiteralPath $wheelPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $receipt.stage = 'dependency_update'
    & $pythonPath -m pip install --no-index --no-deps $wheelPath
    if ($LASTEXITCODE -ne 0) { throw 'The single-package dependency update failed; backend has not been stopped.' }
    & $pythonPath scripts/management_ui_deploy_preflight_20261104.py
    if ($LASTEXITCODE -ne 0) { throw 'Idle boundary changed after package installation; backend has not been stopped.' }
    $latest = Get-Content -LiteralPath (Join-Path $auditPath 'DEPLOY_PREFLIGHT.json') -Raw | ConvertFrom-Json
    if ($latest.backend_pid -ne $ExpectedBackendPid -or $latest.backend_create_time -ne $before.backend_create_time -or
        [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $latest.captured_at -gt 10) { throw 'Preflight identity or freshness changed.' }
    $receipt.stage = 'stop_idle_web_task'
    Stop-ScheduledTask -TaskName $taskName
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (-not (Get-Process -Id $ExpectedBackendPid -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 500
    }
    if (Get-Process -Id $ExpectedBackendPid -ErrorAction SilentlyContinue) { throw 'Original backend did not exit; no forced process termination performed.' }
    $receipt.original_backend_exited = $true
    $receipt.stage = 'start_original_interactive_task'
    Start-ScheduledTask -TaskName $taskName
    $receipt.status = 'restart_requested'
} catch {
    $receipt.status = 'failed'
    $receipt.error_type = $_.Exception.GetType().Name
    throw
} finally {
    $receipt.finished_at = (Get-Date).ToString('o')
    $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $auditPath 'DEPLOYMENT_RECEIPT.json') -Encoding utf8
}
