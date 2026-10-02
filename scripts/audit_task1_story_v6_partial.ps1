param(
    [string]$RenderRoot = "D:\IT\ai_douyin\data\fanqie_promotion\renders\task1_story_v6_full",
    [string]$ReportPath = "D:\IT\ai_douyin\data\qa\task1_story_v6_partial_audit.json"
)

$ErrorActionPreference = "Stop"
$sceneRoot = Join-Path $RenderRoot "scene_assets"
$auditRoot = Join-Path $sceneRoot "audit"
$expected = @(
    "b01_boast", "b02_grab_reaction", "b03_object_question", "b04_confused_answer",
    "b05_age_burst", "b06_pull_away", "b07_protest", "b08_offer_one",
    "b09_offer_two", "b10_offer_three", "b11_flip", "b12_car_reveal",
    "b13_registry_reveal", "b14_certificate", "b15_terms", "b16_escape",
    "b17a_kiss_reaction", "b17b_hunt_order", "b18_cta"
)

$scenes = foreach ($id in $expected) {
    $video = Join-Path $sceneRoot "$id.mp4"
    $meta = Join-Path (Join-Path $auditRoot $id) "audit_meta.json"
    $item = [ordered]@{
        scene_id = $id
        complete = (Test-Path -LiteralPath $video)
        video_path = $video
        video_sha256 = $null
        probe = $null
        audit_meta_path = $meta
        audit_meta_present = (Test-Path -LiteralPath $meta)
        audit_hash_matches = $false
        has_presenter = $null
        musetalk_used = $null
    }
    if ($item.complete) {
        $item.video_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $video).Hash.ToLowerInvariant()
        $probeRaw = & ffprobe -v error -show_entries "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate" -of json $video
        $item.probe = $probeRaw | ConvertFrom-Json
    }
    if ($item.audit_meta_present) {
        $m = Get-Content -Raw -LiteralPath $meta | ConvertFrom-Json
        $item.has_presenter = $m.has_presenter
        $item.musetalk_used = $m.musetalk_used
        $expectedRife = [string]$m.per_stage_sha256.rife_sha256
        $item.audit_hash_matches = $item.complete -and $expectedRife -and ($item.video_sha256 -eq $expectedRife.ToLowerInvariant())
    }
    [pscustomobject]$item
}

$report = [ordered]@{
    schema_version = "fanqie_story_partial_audit/v1"
    generated_at = [DateTime]::UtcNow.ToString("o")
    render_root = $RenderRoot
    expected_scene_count = $expected.Count
    complete_scene_count = @($scenes | Where-Object complete).Count
    all_complete = (@($scenes | Where-Object complete).Count -eq $expected.Count)
    publish_allowed = $false
    block_reason = "partial_render_and_human_review_pending"
    scenes = $scenes
}

$parent = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding utf8
Write-Output $ReportPath
