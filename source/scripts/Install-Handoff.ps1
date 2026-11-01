param([Parameter(Mandatory=$true)][string]$RuntimeRoot, [Parameter(Mandatory=$true)][int]$DiskNumber)
. (Join-Path $RuntimeRoot 'scripts\Common.ps1')
$planHash = Assert-ConfiguredOperation $RuntimeRoot 'installing'
$partition = Get-Partition -DriveLetter C -ErrorAction Stop
if ($partition.DiskNumber -ne $DiskNumber) { throw 'OSD Windows volume is not on confirmed target disk' }
if (!(Test-Path 'C:\Windows\System32\ntoskrnl.exe')) { throw 'Applied Windows image missing' }
Assert-DriverPayload $RuntimeRoot
# Offline injection ensures that the installed OS can access its own boot disk.
Add-WindowsDriver -Path 'C:\' -Driver (Join-Path $RuntimeRoot 'bootstrap-drivers') -Recurse -ErrorAction Stop | Out-Null
# Avoid OSD's generated online SetupComplete launcher: stage three is user-started.
New-Item 'C:\Windows\Setup\Scripts' -ItemType Directory -Force | Out-Null
Set-Content 'C:\Windows\Setup\Scripts\SetupComplete.cmd' "@echo off`r`nexit /b 0`r`n" -Encoding ASCII
$dest = 'C:\OpenDeploy'
New-Item $dest -ItemType Directory -Force | Out-Null
Invoke-Checked 'robocopy.exe' @($RuntimeRoot,$dest,'/E','/XJ','/R:2','/W:1','/NFL','/NDL','/NJH','/NJS') @(0,1,2,3,4,5,6,7)
Assert-DriverPayload $dest
New-Item 'C:\Windows\Panther' -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $RuntimeRoot 'unattend.xml') 'C:\Windows\Panther\unattend.xml' -Force
New-Item 'C:\Users\Public\Desktop' -ItemType Directory -Force | Out-Null
$launcher = '@echo off' + "`r`n" + 'start "" "%SystemDrive%\OpenDeploy\OpenDeploy.exe" --run --stage=drivers --plan "%SystemDrive%\OpenDeploy\plan.json"' + "`r`n"
Set-Content 'C:\Users\Public\Desktop\3-Install-Drivers.cmd' $launcher -Encoding ASCII
$startup = 'C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup'
New-Item $startup -ItemType Directory -Force | Out-Null
# Stage three has a one-click desktop entry, not a second mandatory GUI.
Remove-Item (Join-Path $startup 'OpenDeploy-Drivers.cmd') -ErrorAction SilentlyContinue
Write-State (Join-Path $dest 'deployment-complete.json') @{PlanSHA256=$planHash; DiskNumber=$DiskNumber; MediaId=$env:OPENDEPLOY_MEDIA_ID; ImageIndex=$env:OPENDEPLOY_OS_IMAGE_INDEX; CompletedAt=(Get-Date).ToString('o')}
Invoke-Checked (Join-Path $dest 'OpenDeploy.exe') @('--checkpoint=installed','--plan',(Join-Path $dest 'plan.json'))
$committed = Get-Content (Join-Path $dest 'flow-state.json') -Raw | ConvertFrom-Json
if ($committed.phase -ne 'installed' -or $committed.plan_sha256 -cne $planHash) { throw 'Installed checkpoint did not commit' }
Copy-Item (Join-Path $dest 'flow-state.json') (Join-Path $RuntimeRoot 'flow-state.json') -Force
# OSD is still the sole owner of partitioning, BCDBoot and reboot.
