Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Invoke-Checked {
    param([string]$File, [string[]]$Arguments, [int[]]$SuccessCodes = @(0))
    & $File @Arguments
    if ($LASTEXITCODE -notin $SuccessCodes) { throw "$File failed with exit code $LASTEXITCODE" }
}
function Assert-DriverPayload {
    param([string]$Root)
    $manifest = Get-Content (Join-Path $Root 'drivers-manifest.json') -Raw | ConvertFrom-Json
    if (@($manifest.Files).Count -eq 0) { throw 'No bootstrap drivers in manifest' }
    foreach ($file in $manifest.Files) {
        if ($file.Path -notmatch '^bootstrap-drivers/' -or $file.Path -match '\.\.' -or [IO.Path]::IsPathRooted($file.Path)) { throw 'Invalid driver manifest path' }
        $path = Join-Path $Root $file.Path
        if ((Get-Item -LiteralPath $path).Length -ne $file.Size -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $file.SHA256) { throw "Driver integrity failure: $($file.Path)" }
    }
}
function Assert-DriverSignatures {
    param([string]$Root)
    $catalogs = @(Get-ChildItem (Join-Path $Root 'bootstrap-drivers') -Filter '*.cat' -Recurse)
    if ($catalogs.Count -eq 0) { throw 'No signed driver catalogs' }
    foreach ($catalog in $catalogs) {
        if ((Get-AuthenticodeSignature -LiteralPath $catalog.FullName).Status -ne 'Valid') { throw "Untrusted driver catalog: $($catalog.FullName)" }
    }
}
function Write-State {
    param([string]$Path, [object]$Value)
    $temp = "$Path.new"
    ConvertTo-Json -InputObject $Value -Depth 8 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $Path -Force
}

function Assert-ConfiguredOperation {
    param([string]$Root, [string]$Phase)
    $planPath = Join-Path $Root 'plan.json'
    $stage = if ($Phase -eq 'installing') { 'install' } else { 'drivers' }
    Invoke-Checked (Join-Path $Root 'OpenDeploy.exe') @('--validate-plan',"--stage=$stage",'--plan',$planPath) | Out-Null
    $hash = (Get-FileHash $planPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $flow = Get-Content (Join-Path $Root 'flow-state.json') -Raw | ConvertFrom-Json
    if ($flow.plan_sha256 -cne $hash -or $flow.phase -ne $Phase) { throw 'Sealed plan or stage journal changed' }
    return $hash
}
