param(
    [Parameter(Mandatory=$true)][int]$DiskNumber,
    [Parameter(Mandatory=$true)][string]$DiskSerial,
    [Parameter(Mandatory=$true)][uint64]$DiskSize,
    [Parameter(Mandatory=$true)][string]$ImageFile,
    [Parameter(Mandatory=$true)][string]$RuntimeRoot,
    [int]$ImageIndex = 1,
    [switch]$Rehearsal
)
. (Join-Path $RuntimeRoot 'scripts\Common.ps1')
$planHash = Assert-ConfiguredOperation $RuntimeRoot 'installing'
$approved = Get-Content (Join-Path $RuntimeRoot 'plan.json') -Raw | ConvertFrom-Json
$prepared = Get-Content (Join-Path $RuntimeRoot 'flow-state.json') -Raw | ConvertFrom-Json
if ($DiskSerial -cne $approved.target.serial -or $DiskSize -ne $approved.target.size -or $ImageIndex -ne $approved.image_index) { throw 'Installation arguments differ from sealed plan' }
if ((Get-FileHash -LiteralPath $ImageFile -Algorithm SHA256).Hash.ToLowerInvariant() -cne $prepared.image_sha256) { throw 'Prepared Windows image changed' }

if ($env:SystemDrive -ne 'X:') { throw 'Installation requires the dedicated WinPE' }
$firmware = Get-ItemPropertyValue 'HKLM:\SYSTEM\CurrentControlSet\Control' 'PEFirmwareType'
if ($firmware -ne 2) { throw 'UEFI boot is required' }
$disk = Get-Disk -Number $DiskNumber -ErrorAction Stop
if ($disk.IsBoot -or $disk.IsSystem -or $disk.BusType -eq 'USB') { throw 'Target is a boot/system/USB disk' }
if ($disk.SerialNumber.Trim() -ne $DiskSerial.Trim() -or $disk.Size -ne $DiskSize) { throw 'Confirmed disk identity changed' }
if ($ImageIndex -lt 1 -or !(Test-Path -LiteralPath $ImageFile)) { throw 'Invalid Windows image' }
Assert-DriverPayload $RuntimeRoot
if ($Rehearsal) { Write-Output 'Preflight passed; no disk writes'; exit 0 }
$taskFile = Join-Path $RuntimeRoot 'upstream\OSD\Public\OSDCloud.ps1'
$expectedTask = Join-Path $RuntimeRoot 'osd\patched\OSDCloud.ps1'
if ((Get-FileHash $taskFile).Hash -ne (Get-FileHash $expectedTask).Hash) { throw 'Refusing unpatched OSD task chain' }
if ((Get-FileHash (Join-Path $RuntimeRoot 'upstream\OSD\Public\Start-OSDCloud.ps1')).Hash -ne (Get-FileHash (Join-Path $RuntimeRoot 'osd\patched\Start-OSDCloud.ps1')).Hash) { throw 'Local-image OSD adapter missing' }
$env:PSModulePath = (Join-Path $RuntimeRoot 'upstream') + ';' + $env:PSModulePath
Import-Module (Join-Path $RuntimeRoot 'upstream\OSD\OSD.psd1') -Force -ErrorAction Stop
# This is a disposable worker process. Unexpected upstream input is a failure, never a hidden wait.
function global:Read-Host { throw 'Unexpected interactive input in preconfigured installation' }
$env:OPENDEPLOY_OS_INSTALL_DISK = [string]$DiskNumber
$env:OPENDEPLOY_OS_IMAGE_FILE = (Resolve-Path -LiteralPath $ImageFile).Path
$env:OPENDEPLOY_OS_IMAGE_INDEX = [string]$ImageIndex
$env:OPENDEPLOY_MEDIA_ID = (Get-Content (Join-Path $RuntimeRoot 'media-id.txt') -Raw).Trim()
$Global:MyOSDCloud = @{
    MSCatalogFirmware=$false; MSCatalogDiskDrivers=$false; MSCatalogNetDrivers=$false; MSCatalogScsiDrivers=$false
    WindowsUpdate=$false; WindowsUpdateDrivers=$false; WindowsDefenderUpdate=$false
    SkipAutopilot=$true; SkipAutopilotOOBE=$true; SkipODT=$true; SkipOOBEDeploy=$true
    SetupCompleteNoRestart=$true; DriverPackName='None'
}
Start-OSDCloud -ImageFile $ImageFile -OSImageIndex $ImageIndex -ZTI -SkipAutopilot -SkipODT -Restart
# Successful deployment normally reboots inside OSD. A return without the
# handoff proof is failure, even if PowerShell/OSD returned exit code zero.
if (!(Test-Path 'C:\OpenDeploy\deployment-complete.json')) { throw 'OSD returned without completing OpenDeploy handoff' }
