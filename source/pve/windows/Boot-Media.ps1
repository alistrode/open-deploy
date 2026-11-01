param(
    [string]$UsbSerial,
    [Parameter(Mandatory)][string]$Job,
    [switch]$Restart,
    [switch]$HardDiskIsoUsb,
    [string]$UsbDriveLetter = 'F'
)
$ErrorActionPreference = 'Stop'
if ($HardDiskIsoUsb) {
    $receipt=Get-Content -LiteralPath (Join-Path $Job 'harddisk-usb-receipt.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (!$receipt.completed -or !$receipt.connection_backup_verified) { throw 'Completed installation media and retained identity are required.' }
    $usb=Get-Partition -DriveLetter $UsbDriveLetter | Get-Disk
    if ($usb.BusType -ne 'USB' -or $usb.IsBoot -or $usb.IsSystem -or
        [string]$usb.UniqueId -cne [string]$receipt.usb.unique_id -or [long]$usb.Size -ne [long]$receipt.usb.size) {
        throw 'Prepared USB identity differs; no boot setting was changed.'
    }
    $root=$UsbDriveLetter+':\'
    if (!(Test-Path -LiteralPath (Join-Path $root 'boot\grub\grub.cfg')) -or
        !(Test-Path -LiteralPath (Join-Path $root 'opendeploy\plan.json')) -or
        !(Test-Path -LiteralPath (Join-Path $root 'OpenDeploy-private\ai-private\client_key'))) {
        throw 'Prepared media files are not available.'
    }
    $bcd=Join-Path $env:SystemRoot 'System32\bcdedit.exe'
    $listing=& $bcd /enum firmware
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate existing firmware entries.' }
    $entries=@();$current=$null
    foreach ($line in $listing) {
        $id=[regex]::Match([string]$line,'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}')
        if ($id.Success) {$current=$id.Value}
        if ($current -and [string]$line -match ('partition='+[regex]::Escape($UsbDriveLetter)+':\s*$')) {$entries+=$current}
    }
    if ($entries.Count -ne 1) { throw 'The USB has no unique existing firmware entry; no boot setting was changed.' }
    & $bcd /set $entries[0] path '\EFI\BOOT\BOOTX64.EFI'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot update the existing USB loader path.' }
    & $bcd /set '{fwbootmgr}' bootsequence $entries[0]
    if ($LASTEXITCODE -ne 0) { throw 'Cannot set one-time USB boot.' }
    @{schema=1;firmware_entry=$entries[0];one_time=$true;usb=$receipt.usb;utc=[DateTime]::UtcNow.ToString('o')} |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Job 'firmware-nextboot.json') -Encoding UTF8
    if ($Restart) {
        & (Join-Path $env:SystemRoot 'System32\shutdown.exe') /r /t 60 /d p:4:1 /c 'OpenDeploy: start the prepared PXVIRT installation.'
        if ($LASTEXITCODE -ne 0) { throw 'Restart was not scheduled; one-time USB boot remains selected.' }
    }
    return
}
if (!$UsbSerial) { throw 'The original simulation route requires its configured USB serial.' }
if ((Get-CimInstance Win32_ComputerSystem).Model -notmatch 'VirtualBox') {
    throw 'Guest firmware handoff is restricted to VirtualBox simulation.'
}
$receipt = Get-Content -LiteralPath (Join-Path $Job 'windows-usb-receipt.json') -Raw | ConvertFrom-Json
if (!$receipt.write_completed -or !$receipt.simulation -or $receipt.serial -cne $UsbSerial) {
    throw 'A completed write receipt for the selected simulation media is required.'
}
$disks = @(Get-Disk | Where-Object { $_.SerialNumber -and $_.SerialNumber.Trim() -ceq $UsbSerial })
if ($disks.Count -ne 1 -or $disks[0].IsBoot -or $disks[0].IsSystem -or [long]$disks[0].Size -ne [long]$receipt.size) {
    throw 'Simulation boot media identity differs from the completed write.'
}
$bcd = Join-Path $env:SystemRoot 'System32\bcdedit.exe'
$listing = & $bcd /enum firmware 2>&1
if ($LASTEXITCODE -ne 0) { throw ('Firmware enumeration failed: ' + ($listing -join "`n")) }
$entries = @()
$current = $null
foreach ($line in $listing) {
    $id = [regex]::Match([string]$line, '\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}')
    if ($id.Success) { $current = $id.Value }
    if ($current -and [string]$line -match ('UEFI VBOX HARDDISK\s+' + [regex]::Escape($UsbSerial) + '\s*$')) {
        $entries += $current
    }
}
if ($entries.Count -ne 1) {
    throw 'The selected media has no unique existing UEFI firmware boot entry; its preparation prerequisites are incomplete.'
}
$result = & $bcd /set '{fwbootmgr}' bootsequence $entries[0] 2>&1
if ($LASTEXITCODE -ne 0) { throw ('Setting the one-time guest boot failed: ' + ($result -join "`n")) }
@{schema=1; serial=$UsbSerial; firmware_entry=$entries[0]; one_time=$true; utc=[DateTime]::UtcNow.ToString('o')} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Job 'firmware-nextboot.json') -Encoding UTF8
Write-Host 'One-time PXVIRT media boot selected inside the guest. Permanent boot order is unchanged.'
if ($Restart) {
    & (Join-Path $env:SystemRoot 'System32\shutdown.exe') /r /t 20 /d p:4:1 /c 'OpenDeploy: continue PXVIRT installation from the prepared simulation media.'
    if ($LASTEXITCODE -ne 0) { throw 'Guest restart request failed; the one-time media boot remains selected.' }
}
