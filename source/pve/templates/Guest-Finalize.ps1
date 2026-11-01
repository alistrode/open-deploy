param([switch]$Bootstrap)
$ErrorActionPreference = 'Stop'
$Root = 'C:\OpenDeploy'
trap {
    $detail = [DateTime]::UtcNow.ToString('o') + ' ' + ($_ | Out-String) + [Environment]::NewLine + $_.InvocationInfo.PositionMessage + [Environment]::NewLine + $_.ScriptStackTrace + [Environment]::NewLine
    [IO.File]::AppendAllText((Join-Path $Root 'finalize-errors.log'), $detail)
    throw
}
$plan = Get-Content (Join-Path $Root 'guest-plan.json') -Raw | ConvertFrom-Json
if ((Get-CimInstance Win32_ComputerSystemProduct).UUID -ine $plan.uuid) { throw 'Unexpected VM identity' }
$gate = [Threading.Mutex]::new($false, ('Global\OpenDeploy-Finalize-' + $plan.uuid))
$locked = $false
try {
    try { $locked = $gate.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (!$locked) { exit }
if ($Bootstrap -and (Get-Service Schedule).Status -eq 'Running') {
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
if ($plan.display_language) {
    . (Join-Path $Root 'Install-Language.ps1')
    $needReboot = Install-OpenDeployLanguage $plan.display_language
}
if ((Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Setup\State').ImageState -ne 'IMAGE_STATE_COMPLETE') { exit }
$driverReceipts = Join-Path $Root 'installed-drivers'
New-Item -ItemType Directory -Path $driverReceipts -Force | Out-Null
$devices = @(Get-CimInstance Win32_PnPEntity | Where-Object { $_.Present -and $_.HardwareID })
$drivers = @(Get-ChildItem -LiteralPath $driverRoot[0] -Filter '*.inf' -Recurse | Where-Object { $_.FullName -match '\\w10\\amd64\\' })
foreach ($inf in $drivers) {
    $relative = $inf.FullName.Substring($driverRoot[0].Length)
    $text = Get-Content -LiteralPath $inf.FullName -Raw
    $matching = @(foreach ($device in $devices) {
        foreach ($id in $device.HardwareID) {
            if ($id -and $text.IndexOf([string]$id, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $device; break }
        }
    })
    if (!$matching.Count) { continue }
    $receiptName = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($relative)).Replace('/','_').Replace('+','-')
    $receipt = Join-Path $driverReceipts $receiptName
    if (!@($matching | Where-Object { $_.ConfigManagerErrorCode -ne 0 }).Count) {
        [IO.File]::WriteAllText($receipt, 'matching devices already have working drivers')
        continue
    }
    $driver = Start-Process pnputil.exe -ArgumentList @('/add-driver',('"'+$inf.FullName+'"'),'/install') -Wait -PassThru
    if ($driver.ExitCode -eq 259) {
        $ids = @($matching | ForEach-Object PNPDeviceID)
        $current = @(Get-CimInstance Win32_PnPEntity | Where-Object { $ids -contains $_.PNPDeviceID })
        if ($current.Count -ne $matching.Count -or @($current | Where-Object { $_.ConfigManagerErrorCode -ne 0 }).Count) {
            throw "VirtIO driver installation failed for $relative : 259; matching hardware is not ready"
        }
    } elseif ($driver.ExitCode -notin @(0,3010)) { throw "VirtIO driver installation failed for $relative : $($driver.ExitCode)" }
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
if ($needReboot) { Restart-Computer -Force; exit }
Set-Service QEMU-GA -StartupType Automatic
Start-Service QEMU-GA
if ($Bootstrap) { exit }
$state = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Setup\State').ImageState
if ($state -ne 'IMAGE_STATE_COMPLETE') { exit }
# RDP uses the pre-created account; no automatic login or hard-coded password.
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
$ruleStore = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules'
if (Test-Path $ruleStore) {
    $stored = Get-ItemProperty $ruleStore
    foreach ($rule in $stored.PSObject.Properties) {
        if ($rule.Name -like 'RemoteDesktop-*' -and $rule.Value -is [string]) {
            Set-ItemProperty $ruleStore -Name $rule.Name -Value ($rule.Value -replace 'Active=FALSE', 'Active=TRUE') -Type String
        }
    }
}
$firewall = Get-Service MpsSvc -ErrorAction SilentlyContinue
if ($firewall -and $firewall.Status -eq 'Running') {
    Get-NetFirewallRule | Where-Object { $_.Name -like 'RemoteDesktop-*' } | Enable-NetFirewallRule
} else {
    [IO.File]::AppendAllText((Join-Path $Root 'firewall-capability.log'), ([DateTime]::UtcNow.ToString('o') + ' Firewall service is not running; existing RDP rules enabled in the policy store.' + [Environment]::NewLine))
}
if (!(Get-Service TermService -ErrorAction SilentlyContinue)) { throw 'This image lacks Remote Desktop Services' }
Set-Service TermService -StartupType Automatic
Start-Service TermService
@{id=$plan.id;uuid=$plan.uuid;completed=$true;completedAt=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content (Join-Path $Root 'ready.json.new') -Encoding UTF8
Move-Item (Join-Path $Root 'ready.json.new') (Join-Path $Root 'ready.json') -Force
Unregister-ScheduledTask -TaskName 'OpenDeploy-Finalize' -Confirm:$false -ErrorAction SilentlyContinue


} finally {
    if ($locked) { $gate.ReleaseMutex() }
    $gate.Dispose()
}
