param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

Add-Type -AssemblyName System.IO.Compression.Brotli
$source = [System.IO.File]::OpenRead($InputPath)
try {
    $brotli = [System.IO.Compression.BrotliStream]::new(
        $source,
        [System.IO.Compression.CompressionMode]::Decompress
    )
    try {
        $target = [System.IO.File]::Create($OutputPath)
        try {
            $brotli.CopyTo($target)
        }
        finally {
            $target.Dispose()
        }
    }
    finally {
        $brotli.Dispose()
    }
}
finally {
    $source.Dispose()
}
