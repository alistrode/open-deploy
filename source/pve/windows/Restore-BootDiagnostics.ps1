param(
    [Parameter(Mandatory)][string]$Job,
    [Parameter(Mandatory)][string]$Backup
)
$ErrorActionPreference='Stop'
$r=Get-Content (Join-Path $Job 'harddisk-usb-receipt.json') -Raw|ConvertFrom-Json
$d=Get-Partition -DriveLetter F|Get-Disk
if([string]$d.UniqueId -cne [string]$r.usb.unique_id -or [long]$d.Size -ne [long]$r.usb.size -or $d.BusType -ne 'USB' -or $d.IsBoot -or $d.IsSystem){
    throw 'USB identity differs; restoration not performed'
}
$old=[IO.File]::ReadAllBytes((Join-Path $Backup 'grub.cfg.original'))
$cur=[IO.File]::ReadAllBytes('F:\boot\grub\grub.cfg')
$diag=[IO.File]::ReadAllBytes((Join-Path $Backup 'grub.cfg.diagnostic'))
if([Convert]::ToBase64String($cur) -ne [Convert]::ToBase64String($diag) -and [Convert]::ToBase64String($cur) -ne [Convert]::ToBase64String($old)){
    throw 'Current configuration changed unexpectedly; nothing overwritten'
}
[IO.File]::WriteAllBytes('F:\boot\grub\grub.cfg',$old)
$got=[IO.File]::ReadAllBytes('F:\boot\grub\grub.cfg')
if([Convert]::ToBase64String($got) -ne [Convert]::ToBase64String($old)){throw 'Restore readback mismatch'}
@{restored=$true;bytes=$got.Length;backup=$Backup;reboot_performed=$false;firmware_changed=$false}|ConvertTo-Json -Compress
