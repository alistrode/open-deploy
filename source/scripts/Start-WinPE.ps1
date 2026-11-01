. (Join-Path $PSScriptRoot 'Common.ps1')
try {
    foreach ($name in @('Get-Disk','Get-CimInstance')) { Get-Command $name -ErrorAction Stop | Out-Null }
    $candidates = @(Get-PSDrive -PSProvider FileSystem | Where-Object {
        (Test-Path (Join-Path $_.Root 'OpenDeploy\drivers-manifest.json')) -and (Test-Path (Join-Path $_.Root 'OpenDeploy\image-name.txt')) -and (Test-Path (Join-Path $_.Root 'OpenDeploy\plan.json'))
    })
    if ($candidates.Count -ne 1) { throw 'Expected one OpenDeploy installation USB; remove other installation media' }
    $media = $candidates[0].Root
    Assert-DriverPayload (Join-Path $media 'OpenDeploy')
    Set-Content 'X:\OpenDeploy\media-root.txt' $media -Encoding ASCII
    # Booting the AI-preconfigured PE activates stage two; no GUI data is read.
    Invoke-Checked 'X:\OpenDeploy\OpenDeploy.exe' @('--run','--stage=install','--plan',(Join-Path $media 'OpenDeploy\plan.json'))
} catch {
    $_ | Out-String | Set-Content 'X:\OpenDeploy\startup-error.txt'
    Write-Host $_ -ForegroundColor Red
    # Leave diagnostics visible instead of silently rebooting back into the same failure.
    exit 1
}
