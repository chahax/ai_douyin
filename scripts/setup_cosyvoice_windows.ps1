param(
    [string]$RepoDir = "D:\IT\CosyVoice",
    [string]$EnvName = "cosyvoice310",
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
$envPattern = "^\s*$([regex]::Escape($EnvName))\s"
$envExists = $null -ne ($envList | Select-String -Pattern $envPattern | Select-Object -First 1)
if (-not $envExists) {
    conda create -n $EnvName -y python=3.10
    if ($LASTEXITCODE -ne 0) {
        throw "Conda environment creation failed with exit code $LASTEXITCODE"
    }
}

$envInfo = conda env list --json | ConvertFrom-Json
$envPath = $envInfo.envs |
    Where-Object { (Split-Path -Leaf $_) -eq $EnvName } |
    Select-Object -First 1
if (-not $envPath) {
    throw "Conda environment was not found: $EnvName"
}
$python = Join-Path $envPath "python.exe"

# A cancelled/failed Conda transaction can leave the environment registered
# while python.exe is missing. Repair it in place instead of deleting the env.
if (-not (Test-Path -LiteralPath $python)) {
    conda install -n $EnvName -y --force-reinstall python=3.10
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) {
        throw "Conda Python repair failed with exit code $LASTEXITCODE"
    }
}

# Do not ask Conda to solve and rewrite the whole environment on every run.
& $python -c "import pynini"
if ($LASTEXITCODE -ne 0) {
    conda install -n $EnvName -y -c conda-forge pynini==2.1.6
    if ($LASTEXITCODE -ne 0) {
        throw "Pynini installation failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $RepoDir ".git"))) {
    if (Test-Path -LiteralPath $RepoDir) {
        throw "RepoDir exists but is not a Git repository: $RepoDir"
    }
    git clone --recursive $repoUrl $RepoDir
}
else {
    git -C $RepoDir submodule update --init --recursive
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Conda Python not found: $python"
}

$sourceRequirements = Join-Path $RepoDir "requirements.txt"
$filteredRequirements = Join-Path ([System.IO.Path]::GetTempPath()) "cosyvoice-windows-blackwell-requirements.txt"
Get-Content -LiteralPath $sourceRequirements |
    Where-Object {
        $_ -notmatch "^\s*torch==" -and
        $_ -notmatch "^\s*torchaudio==" -and
        $_ -notmatch "^\s*openai-whisper==" -and
        $_ -notmatch "download\.pytorch\.org/whl/cu121"
    } |
    Set-Content -LiteralPath $filteredRequirements -Encoding UTF8

# RTX 50 series needs a CUDA 12.8-capable PyTorch build. The upstream
# requirements currently pin torch 2.3.1/cu121, which cannot use this GPU.
& $python -m pip install `
    torch==2.8.0 `
    torchaudio==2.8.0 `
    --index-url "https://download.pytorch.org/whl/cu128"
if ($LASTEXITCODE -ne 0) {
    throw "PyTorch installation failed with exit code $LASTEXITCODE"
}

# openai-whisper 20231117 imports pkg_resources while building. Newer
# setuptools releases no longer bundle it, so use a compatible build toolchain
# and disable the temporary isolated build environment for this package.
& $python -m pip install setuptools==80.9.0 wheel
if ($LASTEXITCODE -ne 0) {
    throw "Setuptools compatibility installation failed with exit code $LASTEXITCODE"
}

& $python -m pip install `
    openai-whisper==20231117 `
    --no-build-isolation `
    -i "https://mirrors.aliyun.com/pypi/simple/" `
    --trusted-host "mirrors.aliyun.com"
if ($LASTEXITCODE -ne 0) {
    throw "openai-whisper installation failed with exit code $LASTEXITCODE"
}

& $python -m pip install -r $filteredRequirements `
    -i "https://mirrors.aliyun.com/pypi/simple/" `
    --trusted-host "mirrors.aliyun.com"
if ($LASTEXITCODE -ne 0) {
    throw "CosyVoice dependency installation failed with exit code $LASTEXITCODE"
}

if ($DownloadModel) {
    & $python -m pip install modelscope
    if ($LASTEXITCODE -ne 0) {
        throw "ModelScope installation failed with exit code $LASTEXITCODE"
    }
    $downloadCode = @"
from modelscope import snapshot_download
snapshot_download(
    '$modelId',
    local_dir=r'$modelDir',
)
"@
    & $python -c $downloadCode
    if ($LASTEXITCODE -ne 0) {
        throw "CosyVoice model download failed with exit code $LASTEXITCODE"
    }
}

Write-Host "CosyVoice preparation complete."
Write-Host "Repository: $RepoDir"
Write-Host "Environment: $EnvName"
Write-Host "Model directory: $modelDir"
