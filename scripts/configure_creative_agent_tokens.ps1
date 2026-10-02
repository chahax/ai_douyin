[CmdletBinding()]
param(
    [Security.SecureString]$WriterToken,
    [Security.SecureString]$DirectorToken
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot ".env"
$templatePath = Join-Path $projectRoot ".env.example"
$tempPath = Join-Path $projectRoot ".env.creative-agent.tmp"

function Get-SecretText {
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [Security.SecureString]$SecureValue
    )

    if ($null -eq $SecureValue) {
        $SecureValue = Read-Host $Prompt -AsSecureString
    }
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        $plainValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($plainValue)) {
            throw "Token cannot be empty."
        }
        if ($plainValue.Contains("`r") -or $plainValue.Contains("`n")) {
            throw "Token cannot contain a line break."
        }
        return $plainValue
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Set-EnvValue {
    param(
        [AllowEmptyCollection()][AllowEmptyString()][string[]]$Lines,
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowEmptyString()][string]$Value
    )

    $escapedName = [Regex]::Escape($Name)
    $found = $false
    $updated = @()
    foreach ($line in $Lines) {
        if ($line -match "^$escapedName=") {
            if (-not $found) {
                $updated += "$Name=$Value"
                $found = $true
            }
            continue
        }
        $updated += $line
    }
    if (-not $found) {
        if ($updated.Count -gt 0 -and $updated[-1] -ne "") {
            $updated += ""
        }
        $updated += "$Name=$Value"
    }
    return $updated
}

if (Test-Path -LiteralPath $envPath) {
    $lines = @(Get-Content -LiteralPath $envPath -Encoding UTF8)
}
elseif (Test-Path -LiteralPath $templatePath) {
    $lines = @(Get-Content -LiteralPath $templatePath -Encoding UTF8)
}
else {
    $lines = @()
}

$writerTokenText = Get-SecretText `
    -Prompt "Enter MiniMax M3 API Token (input is hidden)" `
    -SecureValue $WriterToken
$directorTokenText = Get-SecretText `
    -Prompt "Enter DeepSeek V4.1 Flash API Token (input is hidden)" `
    -SecureValue $DirectorToken

$values = [ordered]@{
    WRITER_AGENT_PROVIDER = "minimax"
    WRITER_AGENT_API_STYLE = "openai_chat_completions"
    WRITER_AGENT_API_KEY = $writerTokenText
    WRITER_AGENT_BASE_URL = "https://api.minimaxi.com/v1"
    WRITER_AGENT_ENDPOINT = "/chat/completions"
    WRITER_AGENT_MODEL = "MiniMax-M3"
    DIRECTOR_AGENT_PROVIDER = "deepseek"
    DIRECTOR_AGENT_API_STYLE = "openai_chat_completions"
    DIRECTOR_AGENT_API_KEY = $directorTokenText
    DIRECTOR_AGENT_BASE_URL = "https://api.deepseek.com/v1"
    DIRECTOR_AGENT_ENDPOINT = "/chat/completions"
    DIRECTOR_AGENT_MODEL = "deepseek-flash"
}

foreach ($entry in $values.GetEnumerator()) {
    $lines = @(Set-EnvValue -Lines $lines -Name $entry.Key -Value $entry.Value)
}

$utf8NoBom = [Text.UTF8Encoding]::new($false)
try {
    [IO.File]::WriteAllLines($tempPath, $lines, $utf8NoBom)
    Move-Item -LiteralPath $tempPath -Destination $envPath -Force
}
finally {
    if (Test-Path -LiteralPath $tempPath) {
        Remove-Item -LiteralPath $tempPath -Force
    }
    $writerTokenText = $null
    $directorTokenText = $null
    $WriterToken = $null
    $DirectorToken = $null
}

Write-Host "Saved to local .env: MiniMax M3 writer + DeepSeek V4.1 Flash director."
Write-Host "Tokens were not displayed. .env and the temporary file are ignored by Git."
Write-Host "Next: .\.venv\Scripts\python.exe .\scripts\check_creative_agent_config.py"
