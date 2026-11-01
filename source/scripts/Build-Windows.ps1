param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
$source = Split-Path $PSScriptRoot -Parent
$repo = Split-Path $source -Parent
& (Join-Path $repo 'release\windows-x64\Restore-Runtime.ps1') -Destination $Destination
foreach($name in @('scripts','osd','upstream')) {
    Copy-Item (Join-Path $source $name) $Destination -Recurse -Force
}
Copy-Item (Join-Path $source 'launchers\*.cmd') $Destination -Force
Copy-Item (Join-Path $source 'launchers\1-Prepare.cmd') (Join-Path $Destination 'Start.cmd') -Force
foreach($name in @('dependencies.lock.json')) { Copy-Item (Join-Path $source $name) $Destination -Force }
$env:CGO_ENABLED='0';$env:GOOS='windows';$env:GOARCH='amd64'
Push-Location $source
try {
    & go build -trimpath -buildvcs=false -o (Join-Path $Destination 'OpenDeploy.exe') ./src
    if($LASTEXITCODE -ne 0){throw 'Go build failed'}
}finally{Pop-Location}
@{built_at=(Get-Date).ToString('o');built_from='current local source';executable_sha256=(Get-FileHash (Join-Path $Destination 'OpenDeploy.exe') -Algorithm SHA256).Hash;status='local build; Windows native installation not verified'} | ConvertTo-Json | Set-Content (Join-Path $Destination 'current-build.json') -Encoding UTF8
Write-Output "Built current source into complete runtime: $Destination"
