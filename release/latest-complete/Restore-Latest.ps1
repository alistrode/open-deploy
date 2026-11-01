param([string]$Destination = (Join-Path $PSScriptRoot 'Restored-Latest'))
$ErrorActionPreference = 'Stop'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
$output = Join-Path $Destination $manifest.file
if (Test-Path -LiteralPath $output) { throw 'Output exists; use a new destination.' }
$stream = [IO.File]::Create($output)
try {
    foreach ($part in $manifest.parts) {
        $path = Join-Path $PSScriptRoot $part.name
        if (!(Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -ne [long]$part.bytes) { throw ('Missing or incomplete part: ' + $part.name) }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $part.sha256) { throw ('Part verification failed: ' + $part.name) }
        $source = [IO.File]::OpenRead($path)
        try { $source.CopyTo($stream,8388608) } finally { $source.Dispose() }
    }
} finally { $stream.Dispose() }
if ((Get-Item -LiteralPath $output).Length -ne [long]$manifest.bytes -or (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) { throw 'Complete archive verification failed.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path -LiteralPath (Join-Path $Destination 'OpenDeploy')) { throw 'OpenDeploy already exists; use a new destination.' }
[IO.Compression.ZipFile]::ExtractToDirectory($output,$Destination)
Write-Output ('Complete package restored to ' + $Destination + '. Read OpenDeploy/docs/COMPLETE-DELIVERY.md before use. No installation started.')
