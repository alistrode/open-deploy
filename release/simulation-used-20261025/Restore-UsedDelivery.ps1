param(
    [ValidateSet('Runtime','ISO','PreparedDisk','ChineseLanguage')][string]$Artifact = 'Runtime',
    [string]$Destination = (Join-Path $PSScriptRoot 'Restored-OpenDeploy'),
    [string]$KeyFile,
    [string]$GitHubToken = $env:GH_TOKEN,
    [string]$BaseUrl = 'https://raw.githubusercontent.com/trlstdin/rororororo/refs/heads/projects/open-deploy/release/simulation-used-20261025'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Get-DeliveryFile([string]$Name,[string]$Output) {
    $local = Join-Path $PSScriptRoot $Name
    if (Test-Path -LiteralPath $local) { Copy-Item -LiteralPath $local -Destination $Output; return }
    if (!$GitHubToken -and (Get-Command gh.exe -ErrorAction SilentlyContinue)) {
        $script:GitHubToken = (& gh.exe auth token 2>$null | Out-String).Trim()
    }
    if ($GitHubToken -and $BaseUrl -like 'https://raw.githubusercontent.com/trlstdin/rororororo/*') {
        $uri='https://api.github.com/repos/trlstdin/rororororo/contents/release/simulation-used-20261025/'+[Uri]::EscapeDataString($Name)+'?ref=projects%2Fopen-deploy'
        Invoke-WebRequest -UseBasicParsing -Uri $uri -Headers @{Authorization=('Bearer '+$GitHubToken);Accept='application/vnd.github.raw+json'} -OutFile $Output
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + '/' + $Name) -OutFile $Output
    }
}
if ($Artifact -in @('ISO','PreparedDisk') -and !$KeyFile) { throw 'Provide the separately retained original-media key file' }
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
$Destination = (Resolve-Path -LiteralPath $Destination).Path
$cache = Join-Path $Destination 'download-parts'
New-Item -ItemType Directory -Path $cache -Force | Out-Null
$manifestPath = Join-Path $cache 'delivery-parts.json'
Get-DeliveryFile 'delivery-parts.json' $manifestPath
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($Artifact -ne 'Runtime' -and !@($manifest.artifacts | Where-Object {$_.kind -eq $Artifact}).Count) {
    $mediaPath = Join-Path $cache 'sealed-media-parts.json'
    Get-DeliveryFile 'sealed-media-parts.json' $mediaPath
    $manifest = Get-Content -LiteralPath $mediaPath -Raw | ConvertFrom-Json
}
$item = @($manifest.artifacts | Where-Object {$_.kind -eq $Artifact})
if ($item.Count -ne 1) { throw 'Requested artifact is absent from the delivery' }
$item = $item[0]
$assembled = Join-Path $Destination $item.name
if (Test-Path -LiteralPath $assembled) { throw 'Assembled output already exists; use a new destination' }
$stream = [IO.File]::Create($assembled)
try {
    $index = 0
    foreach ($part in $item.parts) {
        $index++
        Write-Host ('Downloading {0}/{1}: {2}' -f $index,$item.parts.Count,$part.name)
        $path = Join-Path $cache $part.name
        if (!(Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -ne [long]$part.bytes) {
            Get-DeliveryFile $part.name $path
        }
        if ((Get-Item -LiteralPath $path).Length -ne [long]$part.bytes) { throw ('Incomplete download: ' + $part.name) }
        $inputPart = [IO.File]::OpenRead($path)
        try { $inputPart.CopyTo($stream,8388608) } finally {$inputPart.Dispose()}
    }
} finally {$stream.Dispose()}
if ((Get-Item -LiteralPath $assembled).Length -ne [long]$item.bytes) { throw 'Assembled length differs' }
if ($Artifact -eq 'Runtime') {
    if (Test-Path -LiteralPath (Join-Path $Destination 'OpenDeploy')) { throw 'Runtime folder already exists' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($assembled,$Destination)
    Write-Host ('Runtime restored. Start: ' + (Join-Path $Destination 'OpenDeploy\Start-Windows.cmd'))
} elseif ($Artifact -in @('ISO','PreparedDisk')) {
    $restore = Join-Path $cache 'Restore-SealedMedia.ps1'
    Get-DeliveryFile 'Restore-SealedMedia.ps1' $restore
    $name = if ($Artifact -eq 'ISO') {'OpenDeploy-PXVIRT-Original-20261025.iso'} else {'OpenDeploy-Prepared-Media-32G-20261025.vdi'}
    & $restore -EncryptedFile $assembled -KeyFile $KeyFile -OutputFile (Join-Path $Destination $name)
} else {
    Write-Host ('Guest installation input restored: ' + $assembled)
}
