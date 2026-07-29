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

$envInfo = conda env list --json | ConvertFrom-Json
$envPath = $envInfo.envs |
    Where-Object { (Split-Path -Leaf $_) -eq $EnvName } |
    Select-Object -First 1
if (-not $envPath) {
    throw "Conda environment was not found: $EnvName"
}
$python = Join-Path $envPath "python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Conda Python not found: $python"
}

$sourceRequirements = Join-Path $RepoDir "requirements.txt"
$filteredRequirements = Join-Path ([System.IO.Path]::GetTempPath()) "cosyvoice-windows-blackwell-requirements.txt"
Get-Content -LiteralPath $sourceRequirements |
    Where-Object {
        $_ -notmatch "^\s*torch==" -and
        $_ -notmatch "^\s*torchaudio==" -and
        $_ -notmatch "download\.pytorch\.org/whl/cu121"
    } |
    Set-Content -LiteralPath $filteredRequirements -Encoding UTF8

# RTX 50 series needs a CUDA 12.8-capable PyTorch build. The upstream
# requirements currently pin torch 2.3.1/cu121, which cannot use this GPU.
& $python -m pip install `
    torch==2.8.0 `
    torchaudio==2.8.0 `
    --index-url "https://download.pytorch.org/whl/cu128"

& $python -m pip install -r $filteredRequirements `
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
