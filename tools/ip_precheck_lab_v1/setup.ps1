param([string]$BasePython = 'C:\Users\c\.local\bin\python3.11.exe')
$ErrorActionPreference = 'Stop'
$labRoot = $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $labRoot 'cache\uv'
$env:PIP_CACHE_DIR = Join-Path $labRoot 'cache\pip'
$env:TEMP = Join-Path $labRoot 'tmp'
$env:TMP = $env:TEMP
$env:PYTHONNOUSERSITE = '1'
$env:PIP_CONFIG_FILE = 'NUL'
$env:PYTHONPATH = ''
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$labPython = Join-Path $labRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $labPython)) {
    & $BasePython -I -m venv (Join-Path $labRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Independent venv creation failed' }
}
& uv --no-config pip install --python $labPython --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu'
if ($LASTEXITCODE -ne 0) { throw 'CPU Torch install failed' }
& uv --no-config pip install --python $labPython --index-url https://pypi.org/simple 'gliner==0.2.29' 'spacy==3.8.16' 'transformers==4.57.6' 'protobuf==7.36.2'
if ($LASTEXITCODE -ne 0) { throw 'Precheck package install failed' }
& uv --no-config pip check --python $labPython
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed' }
