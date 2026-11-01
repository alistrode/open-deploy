param([string]$Assets = $PSScriptRoot, [string]$Destination = (Join-Path $PSScriptRoot 'OpenDeploy-Windows-Snapshot'))
$ErrorActionPreference = 'Stop'
$manifest = Get-Content -LiteralPath (Join-Path $Assets 'snapshot-release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$zip = Join-Path $Assets 'OpenDeploy-Windows-Snapshot.zip'
$output = [IO.File]::Open($zip,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try {
    foreach ($part in $manifest.parts) {
        $input = [IO.File]::OpenRead((Join-Path $Assets $part.name))
        try { $input.CopyTo($output,4MB) } finally { $input.Dispose() }
    }
    $output.Flush($true)
} finally { $output.Dispose() }
Expand-Archive -LiteralPath $zip -DestinationPath $Destination
Write-Host 'Snapshot extracted. Deployment has not been started.'
