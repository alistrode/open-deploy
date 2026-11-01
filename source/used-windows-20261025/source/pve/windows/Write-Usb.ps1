param([Parameter(Mandatory)][string]$Image, [Parameter(Mandatory)][string]$UsbSerial, [Parameter(Mandatory)][string]$Receipt, [switch]$Simulation)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'RawDisk.ps1')
$Image = (Resolve-Path -LiteralPath $Image).Path
$length = (Get-Item -LiteralPath $Image).Length
if ($Simulation -and (Get-CimInstance Win32_ComputerSystem).Model -notmatch 'VirtualBox') { throw 'Virtual media writing is restricted to a VirtualBox guest' }
function Bound-Disk {
    $matches = @(Get-Disk | Where-Object { $_.SerialNumber -and $_.SerialNumber.Trim() -ceq $UsbSerial })
    if ($matches.Count -ne 1) { throw 'USB serial missing or not unique' }
    $disk = $matches[0]
    if ((!$Simulation -and $disk.BusType -ne 'USB') -or $disk.IsBoot -or $disk.IsSystem -or $disk.IsReadOnly -or $disk.Size -lt $length) { throw 'Refusing non-USB, system, boot, read-only or undersized disk' }
    return $disk
}
$disk = Bound-Disk
$binding = @{serial=$UsbSerial; unique_id=[string]$disk.UniqueId; size=[long]$disk.Size; image_bytes=$length; simulation=[bool]$Simulation}
$device = '\\.\PhysicalDrive' + $disk.Number
if (Test-Path -LiteralPath $Receipt) {
    $previous = Get-Content -LiteralPath $Receipt -Raw | ConvertFrom-Json
    foreach ($key in $binding.Keys) { if ([string]$previous.$key -cne [string]$binding[$key]) { throw 'Completed USB binding or image changed; refusing to rewrite' } }
    Write-Host 'USB write already completed; continuing without rewriting.'
    return
}
$again = Bound-Disk
if ($again.Number -ne $disk.Number -or $again.UniqueId -cne $disk.UniqueId -or $again.Size -ne $disk.Size) { throw 'USB identity changed' }
# Clear-Disk dismounts the selected USB volumes. No machine-global automount change.
if ($disk.PartitionStyle -ne 'RAW') { Clear-Disk -Number $disk.Number -RemoveData -RemoveOEM -Confirm:$false }
$again = Bound-Disk
if ($again.Number -ne $disk.Number -or $again.Size -ne $disk.Size) { throw 'USB changed after partition removal' }
$write = New-Object IO.FileStream($device,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite,1048576,[IO.FileOptions]::WriteThrough)
try {
    if ([OpenDeployRawDisk]::Length($write.SafeFileHandle) -ne $disk.Size -or (!$Simulation -and [OpenDeployRawDisk]::UsbSerial($write.SafeFileHandle) -cne $UsbSerial)) { throw 'Physical handle identity or capacity differs' }
    # Remove stale backup GPT metadata outside the image.
    if ($disk.Size - $length -ge 1MB) { $write.Position=$disk.Size-1MB; $write.Write((New-Object byte[] (1MB)),0,1MB) }
    $write.Position=0
    $imageStream = [IO.File]::OpenRead($Image)
    try { $imageStream.CopyTo($write,4MB) } finally { $imageStream.Dispose() }
    $write.Flush($true)
} finally { $write.Dispose() }
$binding.unique_id = [string](Bound-Disk).UniqueId
$binding.write_completed = $true
$binding | ConvertTo-Json | Set-Content -LiteralPath ($Receipt+'.new') -Encoding UTF8
Move-Item -LiteralPath ($Receipt+'.new') -Destination $Receipt
Write-Host 'USB write completed.'
