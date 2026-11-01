param(
    [Parameter(Mandatory)][string]$BundleRoot,
    [string]$Image = 'E:\OpenDeploy-PXVIRT.iso',
    [string]$UsbDriveLetter = 'F',
    [Parameter(Mandatory)][string]$PythonPath,
    [string]$TargetDiskSerial,
    [string]$Job = (Join-Path $env:LOCALAPPDATA 'OpenDeploy\PXVIRT-harddisk-job')
)
$ErrorActionPreference = 'Stop'
# Reuse the original project configuration; no additional dialog or selection.
$configPath = Join-Path $Job 'plan.json'
if (!$TargetDiskSerial -and (Test-Path -LiteralPath $configPath)) {
    $configuration = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($configuration.manual_install) { throw 'Rewrite the old manual-install configuration before preparation.' }
    $TargetDiskSerial = [string]$configuration.host.disk_serial
}
if ([string]::IsNullOrWhiteSpace($TargetDiskSerial) -or $TargetDiskSerial -eq 'SELECT-IN-INSTALLER' -or $TargetDiskSerial -match '[*?\[\]\r\n]') {
    throw 'Complete the target disk configuration first. No interactive disk selector is used.'
}
$BundleRoot = (Resolve-Path -LiteralPath $BundleRoot).Path
$Image = (Resolve-Path -LiteralPath $Image).Path
if ($Image -cne 'E:\OpenDeploy-PXVIRT.iso' -or $UsbDriveLetter -cne 'F') {
    throw 'This entry is restricted to the requested E: ISO and F: installation USB.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (!(New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this existing project entry from an administrator terminal.'
}
$partition = Get-Partition -DriveLetter $UsbDriveLetter
$usb = $partition | Get-Disk
if ($usb.BusType -ne 'USB' -or $usb.IsBoot -or $usb.IsSystem -or $usb.IsReadOnly) {
    throw 'F: must be a writable non-system USB disk.'
}
$binding = @{ number=[int]$usb.Number; unique_id=[string]$usb.UniqueId; size=[long]$usb.Size }
$boot = Join-Path $BundleRoot 'boot-assets'
$manifest = Get-Content -LiteralPath (Join-Path $boot 'boot-manifest.json') -Raw | ConvertFrom-Json
if ($binding.size -ne $manifest.disk_bytes) { throw 'Boot layout is bound to another USB capacity.' }
$users = @(Get-ChildItem -LiteralPath ($UsbDriveLetter+':\') -Force | Where-Object { $_.Name -notin @('System Volume Information','$RECYCLE.BIN') })
$root=$UsbDriveLetter+':\'
$ownedNames=@('EFI','boot','opendeploy','OpenDeploy-private','OpenDeploy-USB.marker')
$foreign=@($users | Where-Object {$_.Name -notin $ownedNames})
$reuse=(Test-Path -LiteralPath (Join-Path $root 'OpenDeploy-USB.marker')) -and
       (Test-Path -LiteralPath (Join-Path $root 'EFI\BOOT\BOOTX64.EFI')) -and !$foreign.Count
if ($users.Count -and !$reuse) { throw 'The USB contains files outside this project; they were retained.' }

$sourceDisk = Get-Partition -DriveLetter E | Get-Disk
if ($sourceDisk.Number -eq $binding.number) { throw 'The source ISO and boot USB must be different devices.' }
$volumeInfo = (& fsutil.exe fsinfo ntfsinfo E: | Out-String)
$match = [regex]::Match($volumeInfo, '0x([0-9A-Fa-f]{16})')
if (!$match.Success) { throw 'Cannot read the exact NTFS source volume serial.' }
$env:PATH = (Join-Path $BundleRoot 'runtime\usr\bin')+';'+$env:SystemRoot+'\System32;'+$env:PATH
$env:MSYSTEM = 'MSYS'; $env:CHERE_INVOKING='1'; $env:PYTHONDONTWRITEBYTECODE='1'
New-Item -ItemType Directory -Path $Job -Force | Out-Null
$tree = Join-Path $Job 'usb-tree'
$buildArgs = @((Join-Path $PSScriptRoot 'prepare_harddisk.py'),'--bundle',$BundleRoot,'--iso',$Image,
    '--job',$Job,'--usb-tree',$tree,'--source-uuid',$match.Groups[1].Value)
if ($TargetDiskSerial) { $buildArgs += @('--disk-serial',$TargetDiskSerial) }
& $PythonPath @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'Original installer preparation failed; the USB has not been changed.' }
# Preserve the existing connection identity before any physical USB write.
& $PythonPath (Join-Path $PSScriptRoot 'preserve_connection.py') --job $Job --usb $tree
if ($LASTEXITCODE -ne 0) { throw 'Connection identity backup failed; USB was not changed.' }
$treeBytes = (Get-ChildItem -LiteralPath $tree -File -Recurse | Measure-Object Length -Sum).Sum
if ($treeBytes + $manifest.prefix_bytes + 16MB -gt $binding.size) { throw 'The installation boot files do not fit this USB.' }
function Bound-Usb {
    $current = Get-Disk -Number $binding.number
    if ($current.BusType -ne 'USB' -or $current.IsBoot -or $current.IsSystem -or $current.IsReadOnly -or
        [string]$current.UniqueId -cne $binding.unique_id -or [long]$current.Size -ne $binding.size) {
        throw 'The selected USB identity changed.'
    }
    return $current
}
if (!$reuse) {
. (Join-Path $PSScriptRoot 'RawDisk.ps1')
$backup = Join-Path $Job 'usb-before'
if (Test-Path -LiteralPath $backup) { throw 'A prior USB operation exists; inspect its receipt before rewriting.' }
New-Item -ItemType Directory -Path $backup | Out-Null
$binding | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'binding.json') -Encoding UTF8
[void](Bound-Usb)
$device='\\.\PhysicalDrive'+$binding.number
$reader=New-Object IO.FileStream($device,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
try {
    if ([OpenDeployRawDisk]::Length($reader.SafeFileHandle) -ne $binding.size) { throw 'Physical USB capacity differs.' }
    $bytes=New-Object byte[] (1MB)
    if ($reader.Read($bytes,0,$bytes.Length) -ne $bytes.Length) { throw 'Incomplete USB metadata backup.' }
    [IO.File]::WriteAllBytes((Join-Path $backup 'first-1MiB.bin'),$bytes)
    $reader.Position=$binding.size-1MB
    if ($reader.Read($bytes,0,$bytes.Length) -ne $bytes.Length) { throw 'Incomplete USB tail backup.' }
    [IO.File]::WriteAllBytes((Join-Path $backup 'last-1MiB.bin'),$bytes)
} finally { $reader.Dispose() }
$prefix = Join-Path $boot 'usb-prefix.img.gz'
$plain = Join-Path $Job 'usb-prefix.img'
$input=[IO.File]::OpenRead($prefix)
$gzip=New-Object IO.Compression.GZipStream($input,[IO.Compression.CompressionMode]::Decompress)
$output=[IO.File]::Create($plain)
try { $gzip.CopyTo($output) } finally { $output.Dispose();$gzip.Dispose();$input.Dispose() }
if ((Get-Item -LiteralPath $plain).Length -ne $manifest.prefix_bytes -or
    (Get-FileHash -LiteralPath $plain -Algorithm SHA256).Hash.ToLowerInvariant() -cne $manifest.sha256) {
    throw 'Boot-loader artifact is incomplete.'
}
[void](Bound-Usb)
Clear-Disk -Number $binding.number -RemoveData -RemoveOEM -Confirm:$false
[void](Bound-Usb)
$write=New-Object IO.FileStream($device,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite,1048576,[IO.FileOptions]::WriteThrough)
try {
    if ([OpenDeployRawDisk]::Length($write.SafeFileHandle) -ne $binding.size) { throw 'Opened USB handle capacity differs.' }
    $write.Position=$binding.size-1MB; $write.Write((New-Object byte[] (1MB)),0,1MB)
    $write.Position=0; $input=[IO.File]::OpenRead($plain)
    try { $input.CopyTo($write,4MB) } finally { $input.Dispose() }
    $write.Flush($true)
} finally { $write.Dispose() }
Update-Disk -Number $binding.number
Update-HostStorageCache
for($attempt=0;$attempt -lt 50;$attempt++) {
    $newPartition=Get-Partition -DiskNumber $binding.number -ErrorAction SilentlyContinue | Where-Object PartitionNumber -eq 1
    if($newPartition) { break }
    Start-Sleep -Milliseconds 200
}
if(!$newPartition) { throw 'The written USB partition has not appeared; do not repeat the raw write.' }
if($newPartition.DriveLetter -ne $UsbDriveLetter) {
    Set-Partition -DiskNumber $binding.number -PartitionNumber 1 -NewDriveLetter $UsbDriveLetter
}
$root=$UsbDriveLetter+':\'
for($attempt=0;$attempt -lt 50;$attempt++) {
    if(Test-Path -LiteralPath (Join-Path $root 'EFI\BOOT\BOOTX64.EFI')) { break }
    Start-Sleep -Milliseconds 200
}
if(!(Test-Path -LiteralPath (Join-Path $root 'EFI\BOOT\BOOTX64.EFI'))) { throw 'The EFI loader is not readable; do not rewrite the disk blindly.' }
}
[void](Bound-Usb)
Copy-Item -Path (Join-Path $tree '*') -Destination $root -Recurse -Force
& $PythonPath (Join-Path $PSScriptRoot 'preserve_connection.py') --job $Job --usb $root
if ($LASTEXITCODE -ne 0) { throw 'Connection identity backup failed. Installation media is not ready.' }
$receipt=@{completed=$true;usb=$binding;source_uuid=$match.Groups[1].Value;iso=$Image;
    iso_bytes=(Get-Item -LiteralPath $Image).Length;usb_payload_bytes=$treeBytes;
    manual_install=$false;reused_boot_layout=$reuse;ai_private=(Join-Path $root 'OpenDeploy-private\ai-private');connection_backup_verified=$true;reboot_performed=$false}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Job 'harddisk-usb-receipt.json') -Encoding UTF8
$receipt | ConvertTo-Json -Depth 6
