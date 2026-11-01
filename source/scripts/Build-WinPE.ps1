param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)][string]$Bundle, [Parameter(Mandatory=$true)][string]$SourceISO)
. (Join-Path $PSScriptRoot 'Common.ps1')
Set-Content (Join-Path $Bundle 'OpenDeploy\media-id.txt') ([guid]::NewGuid().ToString('D')) -Encoding ASCII
Assert-DriverPayload $Root
Assert-DriverSignatures $Root
$lock = Get-Content (Join-Path $Root 'dependencies.lock.json') -Raw | ConvertFrom-Json
$kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Assessment and Deployment Kit'
$pe = Join-Path $kits 'Windows Preinstallation Environment'
$oscdimg = Join-Path $kits 'Deployment Tools\amd64\Oscdimg\oscdimg.exe'
$dism = Join-Path $kits 'Deployment Tools\amd64\DISM\dism.exe'
$cache = Join-Path $Root 'dependency-cache'
New-Item $cache -ItemType Directory -Force | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
foreach ($item in @(@{Spec=$lock.adk; Check=$oscdimg; Name='adksetup.exe'}, @{Spec=$lock.winpe; Check=(Join-Path $pe 'amd64\en-us\winpe.wim'); Name='adkwinpesetup.exe'})) {
    if (!(Test-Path $item.Check)) {
        $installer = Join-Path $cache $item.Name
        if (!(Test-Path $installer) -or (Get-FileHash $installer -Algorithm SHA256).Hash -ine $item.Spec.sha256) {
            Invoke-WebRequest -Uri $item.Spec.url -OutFile "$installer.partial" -UseBasicParsing
            if ((Get-FileHash "$installer.partial" -Algorithm SHA256).Hash -ine $item.Spec.sha256) { throw 'ADK installer checksum failed' }
            Move-Item "$installer.partial" $installer -Force
        }
        if ((Get-AuthenticodeSignature $installer).Status -ne 'Valid') { throw 'ADK installer signature invalid' }
        $proc = Start-Process $installer -ArgumentList @('/quiet','/norestart','/ceip','off','/features',$item.Spec.feature) -Wait -PassThru
        if ($proc.ExitCode -notin @(0,3010)) { throw "ADK installation failed: $($proc.ExitCode)" }
        if (!(Test-Path $item.Check)) { throw "ADK component missing after setup: $($item.Check)" }
    }
}
# Mount the Windows ISO only on the full host OS, extract its image once,
# and let the dedicated PE read the WIM/ESD directly from USB.
$existing = Get-DiskImage -ImagePath $SourceISO -ErrorAction SilentlyContinue
$mountedHere = !$existing -or !$existing.Attached
try {
    if ($mountedHere) { $diskImage = Mount-DiskImage -ImagePath $SourceISO -PassThru -ErrorAction Stop } else { $diskImage = $existing }
    $isoVolume = @($diskImage | Get-Volume | Where-Object DriveLetter)
    if ($isoVolume.Count -ne 1) { throw 'Cannot identify Windows ISO volume' }
    $imagePath = "$($isoVolume[0].DriveLetter):\sources\install.wim"
    $imageName = 'Windows.wim'
    if (!(Test-Path $imagePath)) { $imagePath = "$($isoVolume[0].DriveLetter):\sources\install.esd"; $imageName = 'Windows.esd' }
    if (!(Test-Path $imagePath)) { throw 'ISO must contain install.wim or install.esd; split SWM is unsupported' }
    $approvedPlan = Get-Content (Join-Path $Bundle 'OpenDeploy\plan.json') -Raw | ConvertFrom-Json
    $imageInfo = Get-WindowsImage -ImagePath $imagePath -Index $approvedPlan.image_index -ErrorAction Stop
    if ([string]$imageInfo.Architecture -notin @('9','x64','amd64')) { throw 'Only x64 Windows images are supported' }
    $language = ''
    if ($imageInfo.PSObject.Properties['DefaultLanguage']) { $language = [string]$imageInfo.DefaultLanguage }
    if (!$language -and $imageInfo.PSObject.Properties['Languages']) { $language = [string](@($imageInfo.Languages)[0]) }
    $language = ($language -replace '\s*\(Default\).*$', '').Trim()
    if (!$language) { throw 'Cannot determine Windows image language' }
    $null = [Globalization.CultureInfo]::GetCultureInfo($language)
    $unattendPath = Join-Path $Bundle 'OpenDeploy\unattend.xml'
    (Get-Content $unattendPath -Raw).Replace('__IMAGE_LANGUAGE__',$language) | Set-Content $unattendPath -Encoding UTF8
    $images = Join-Path $Bundle 'Images'
    New-Item $images -ItemType Directory -Force | Out-Null
    # Remove only the previous staged image, never the user's ISO.
    Get-ChildItem $images -File | Remove-Item -Force
    Copy-Item -LiteralPath $imagePath -Destination (Join-Path $images $imageName)
    Set-Content (Join-Path $Bundle 'OpenDeploy\image-name.txt') $imageName -Encoding ASCII
} finally { if ($mountedHere) { Dismount-DiskImage -ImagePath $SourceISO -ErrorAction Continue | Out-Null } }
# Copy a matched ADK image and optional components; never service an arbitrary ISO's boot.wim.
$work = Join-Path $Root 'pe-build'
$media = Join-Path $work 'media'
$mount = Join-Path $work 'mount'
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item $mount -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $pe 'amd64\Media') $media -Recurse
New-Item (Join-Path $media 'sources') -ItemType Directory -Force | Out-Null
$wim = Join-Path $media 'sources\boot.wim'
Copy-Item (Join-Path $pe 'amd64\en-us\winpe.wim') $wim
(Get-Item $wim).IsReadOnly = $false
$mounted = $false
try {
    Invoke-Checked $dism @('/Mount-Image',"/ImageFile:$wim",'/Index:1',"/MountDir:$mount")
    $mounted = $true
    # Dependency order follows OSD/Public/Functions/WindowsAdk.ps1; omit unrelated optional features.
    $ocs = Join-Path $pe 'amd64\WinPE_OCs'
    foreach ($name in @('WinPE-WMI','WinPE-NetFx','WinPE-Scripting','WinPE-PowerShell','WinPE-DismCmdlets','WinPE-StorageWMI')) {
        Invoke-Checked $dism @("/Image:$mount",'/Add-Package',"/PackagePath:$(Join-Path $ocs "$name.cab")")
        Invoke-Checked $dism @("/Image:$mount",'/Add-Package',"/PackagePath:$(Join-Path $ocs "en-us\${name}_en-us.cab")")
    }
    Invoke-Checked $dism @("/Image:$mount",'/Add-Package',"/PackagePath:$(Join-Path $ocs 'WinPE-FontSupport-ZH-CN.cab')")
    Invoke-Checked $dism @("/Image:$mount",'/Add-Driver',"/Driver:$(Join-Path $Root 'bootstrap-drivers')",'/Recurse')
    Copy-Item "$env:SystemRoot\System32\curl.exe" (Join-Path $mount 'Windows\System32\curl.exe')
    $app = Join-Path $mount 'OpenDeploy'
    New-Item $app -ItemType Directory -Force | Out-Null
    Copy-Item (Join-Path $Root 'OpenDeploy.exe') $app
    New-Item (Join-Path $app 'scripts') -ItemType Directory -Force | Out-Null
    Copy-Item (Join-Path $Root 'scripts\Start-WinPE.ps1') (Join-Path $app 'scripts')
    Copy-Item (Join-Path $Root 'scripts\Common.ps1') (Join-Path $app 'scripts')
    Set-Content (Join-Path $mount 'Windows\System32\startnet.cmd') "@echo off`r`nwpeinit`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File X:\OpenDeploy\scripts\Start-WinPE.ps1`r`n" -Encoding ASCII
    Invoke-Checked $dism @('/Unmount-Image',"/MountDir:$mount",'/Commit')
    $mounted = $false
} finally { if ($mounted) { & $dism /Unmount-Image "/MountDir:$mount" /Discard | Out-Null } }
$boot = Join-Path $pe 'amd64\Media\efi\microsoft\boot\efisys.bin'
Invoke-Checked $oscdimg @('-m','-o','-u2','-udfver102',"-bootdata:1#pEF,e,b$boot",$media,(Join-Path $Bundle 'ISO\OpenDeployPE.iso'))
if (!(Test-Path (Join-Path $Bundle 'ISO\OpenDeployPE.iso'))) { throw 'Boot ISO not generated' }

Write-State (Join-Path $Bundle 'OpenDeploy\pe-build-info.json') @{BuiltAt=(Get-Date).ToString('o');DismVersion=(Get-Item $dism).VersionInfo.FileVersion;WinPEWimSHA256=(Get-FileHash (Join-Path $pe 'amd64\en-us\winpe.wim')).Hash;DriverManifestSHA256=(Get-FileHash (Join-Path $Root 'drivers-manifest.json')).Hash}
