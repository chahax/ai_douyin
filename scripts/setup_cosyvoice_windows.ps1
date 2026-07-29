param(
    [string]$RepoDir = "D:\IT\CosyVoice",
    [string]$EnvName = "cosyvoice",
    [switch]$DownloadModel
)

$ErrorActionPreference = "Stop"
$repoUrl = "https://github.com/QwenAudio/CosyVoice.git"
$modelId = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
$modelDir = Join-Path $RepoDir "pretrained_models\Fun-CosyVoice3-0.5B"

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "conda is not available"
}

$envList = conda env list
if ($envList -notmatch "(?m)^\s*$([regex]::Escape($EnvName))\s") {
    conda create -n $EnvName -y python=3.10
}

conda install -n $EnvName -y -c conda-forge pynini==2.1.6

if (-not (Test-Path -LiteralPath (Join-Path $RepoDir ".git"))) {
    if (Test-Path -LiteralPath $RepoDir) {
        throw "RepoDir exists but is not a Git repository: $RepoDir"
    }
    git clone --recursive $repoUrl $RepoDir
}
else {
    git -C $RepoDir submodule update --init --recursive
}

$python = "C:\Users\c\.conda\envs\$EnvName\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Conda Python not found: $python"
}

& $python -m pip install -r (Join-Path $RepoDir "requirements.txt") `
    -i "https://mirrors.aliyun.com/pypi/simple/" `
    --trusted-host "mirrors.aliyun.com"

if ($DownloadModel) {
    & $python -m pip install modelscope
    $downloadCode = @"
from modelscope import snapshot_download
snapshot_download(
    '$modelId',
    local_dir=r'$modelDir',
)
"@
    & $python -c $downloadCode
}

Write-Host "CosyVoice preparation complete."
Write-Host "Repository: $RepoDir"
Write-Host "Environment: $EnvName"
Write-Host "Model directory: $modelDir"
