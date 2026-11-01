param([switch]$Bootstrap)
$ErrorActionPreference = 'Stop'
$Root = 'C:\OpenDeploy'
$plan = Get-Content (Join-Path $Root 'guest-plan.json') -Raw | ConvertFrom-Json
if ((Get-CimInstance Win32_ComputerSystemProduct).UUID -ine $plan.uuid) { throw 'Unexpected VM identity' }
if ($Bootstrap) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\OpenDeploy\Guest-Finalize.ps1'
    $triggers = @(New-ScheduledTaskTrigger -AtStartup; New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 2))
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable
    Register-ScheduledTask -TaskName 'OpenDeploy-Finalize' -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Force | Out-Null
}
# Do not trigger Windows Update during guest installation.
$updatePolicy = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
New-Item -Path $updatePolicy -Force | Out-Null
Set-ItemProperty -Path $updatePolicy -Name NoAutoUpdate -Value 1 -Type DWord
if (Get-Service wuauserv -ErrorAction SilentlyContinue) {
    Stop-Service wuauserv -Force
    Set-Service wuauserv -StartupType Disabled
}
$volumes = @(Get-Volume | Where-Object DriveLetter)
$driverRoot = @($volumes | ForEach-Object { $_.DriveLetter + ':\' } | Where-Object { Test-Path (Join-Path $_ 'vioserial\w10\amd64\vioser.inf') })
if ($driverRoot.Count -ne 1) { throw 'Select one VirtIO driver ISO' }
$needReboot = $false
$driverReceipts = Join-Path $Root 'installed-drivers'
New-Item -ItemType Directory -Path $driverReceipts -Force | Out-Null
$drivers = @(Get-ChildItem -LiteralPath $driverRoot[0] -Filter '*.inf' -Recurse | Where-Object { $_.FullName -match '\\w10\\amd64\\' })
foreach ($inf in $drivers) {
    $relative = $inf.FullName.Substring($driverRoot[0].Length)
    $receiptName = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($relative)).Replace('/','_').Replace('+','-')
    $receipt = Join-Path $driverReceipts $receiptName
    if (Test-Path -LiteralPath $receipt) { continue }
    $driver = Start-Process pnputil.exe -ArgumentList @('/add-driver',('"'+$inf.FullName+'"'),'/install') -Wait -PassThru
    if ($driver.ExitCode -notin @(0,3010)) { throw "VirtIO driver installation failed: $($driver.ExitCode)" }
    $needReboot = $needReboot -or $driver.ExitCode -eq 3010
    [IO.File]::WriteAllText($receipt, 'installed')
}
$msi = @($volumes | ForEach-Object { Join-Path ($_.DriveLetter + ':\') 'guest-agent\qemu-ga-x86_64.msi' } | Where-Object { Test-Path $_ })
if (!(Get-Service QEMU-GA -ErrorAction SilentlyContinue)) {
    if ($msi.Count -ne 1) { throw 'One VirtIO ISO with x64 QEMU guest agent is required' }
    $p = Start-Process msiexec.exe -ArgumentList @('/i',('"'+$msi[0]+'"'),'/qn','/norestart') -Wait -PassThru
    if ($p.ExitCode -notin @(0,3010)) { throw "Guest Agent installation failed: $($p.ExitCode)" }
    $needReboot = $needReboot -or $p.ExitCode -eq 3010
}
if ($needReboot) { if (!$Bootstrap) { Restart-Computer -Force }; exit }
Set-Service QEMU-GA -StartupType Automatic
Start-Service QEMU-GA
if ($Bootstrap) { exit }
$state = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Setup\State').ImageState
if ($state -ne 'IMAGE_STATE_COMPLETE') { exit }
# RDP uses the pre-created account; no automatic login or hard-coded password.
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
Get-NetFirewallRule | Where-Object { $_.Name -like 'RemoteDesktop-*' } | Enable-NetFirewallRule
if (!(Get-Service TermService -ErrorAction SilentlyContinue)) { throw 'This image lacks Remote Desktop Services' }
Start-Service TermService
@{id=$plan.id;uuid=$plan.uuid;completed=$true;completedAt=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content (Join-Path $Root 'ready.json.new') -Encoding UTF8
Move-Item (Join-Path $Root 'ready.json.new') (Join-Path $Root 'ready.json') -Force
Unregister-ScheduledTask -TaskName 'OpenDeploy-Finalize' -Confirm:$false -ErrorAction SilentlyContinue
