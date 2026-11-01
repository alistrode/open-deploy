param(
    [Parameter(Mandatory)][string]$SourceIso,
    [Parameter(Mandatory)][string]$TargetDiskSerial,
    [Parameter(Mandatory)][string]$MediaDiskSerial,
    [string]$Job = (Join-Path $env:LOCALAPPDATA 'OpenDeploy\PXVIRT-vm-job'),
    [switch]$RestartToMedia
)
$ErrorActionPreference = 'Stop'
try {
    # Run inside a fresh full clone of the Windows master, never on its host.
    if ((Get-CimInstance Win32_ComputerSystem).Model -notmatch 'VirtualBox') {
        throw 'This entry requires a VirtualBox Windows guest cloned from the master.'
    }
    foreach ($serial in @($TargetDiskSerial, $MediaDiskSerial)) {
        if ([string]::IsNullOrWhiteSpace($serial) -or $serial -cne $serial.Trim() -or
            $serial -eq 'SELECT-IN-INSTALLER' -or $serial -match '[*?\[\]\r\n]') {
            throw 'Exact, nonempty disk serials are required.'
        }
    }
    $target = @(Get-Disk | Where-Object { $_.SerialNumber -and $_.SerialNumber.Trim() -ceq $TargetDiskSerial })
    $media = @(Get-Disk | Where-Object { $_.SerialNumber -and $_.SerialNumber.Trim() -ceq $MediaDiskSerial })
    if ($target.Count -ne 1 -or $media.Count -ne 1) { throw 'Each configured disk serial must identify exactly one disk.' }
    if ($target[0].Number -eq $media[0].Number) { throw 'Target and installation medium must be different disks.' }
    if ($target[0].IsReadOnly -or $target[0].IsOffline -or $media[0].IsReadOnly -or $media[0].IsOffline -or
        $media[0].IsBoot -or $media[0].IsSystem) { throw 'Disks must be online and writable; the medium cannot be the Windows boot/system disk.' }
    if ($target[0].BusType -eq 'USB' -or $media[0].BusType -eq 'USB') {
        throw 'This simulation entry requires dedicated virtual disks, not USB passthrough devices.'
    }
    $SourceIso = (Resolve-Path -LiteralPath $SourceIso).Path
    if ([IO.Path]::GetExtension($SourceIso) -ine '.iso' -or !(Test-Path -LiteralPath $SourceIso -PathType Leaf)) {
        throw 'An existing PXVIRT source ISO is required.'
    }
    $sourceDrive = [IO.Path]::GetPathRoot($SourceIso)
    if ($sourceDrive -notmatch '^[A-Za-z]:\\$') { throw 'Stage the ISO on a local guest volume first.' }
    $sourceDisk = Get-Partition -DriveLetter $sourceDrive.Substring(0,1) | Get-Disk
    if ($sourceDisk.Number -eq $media[0].Number) { throw 'The source ISO cannot reside on the medium that will be erased.' }
    if ($RestartToMedia -and $env:firmware_type -ine 'UEFI') { throw 'Automatic guest handoff requires UEFI firmware.' }
    $Root = $PSScriptRoot
    foreach ($name in @('Start-Windows.ps1','Write-Usb.ps1','RawDisk.ps1','Boot-Media.ps1','python\python.exe','runtime\usr\bin\xorriso.exe','assets\linux-x64.tar.gz')) {
        if (!(Test-Path -LiteralPath (Join-Path $Root $name))) { throw ('Incomplete bundle: ' + $name) }
    }
    # Passing both serials avoids the legacy visual configuration dialog.
    & (Join-Path $Root 'Start-Windows.ps1') -SourceIso $SourceIso -TargetDiskSerial $TargetDiskSerial `
        -UsbSerial $MediaDiskSerial -Simulation -RestartToMedia:$RestartToMedia -Job $Job
    exit $LASTEXITCODE
} catch {
    Write-Error -Message $_ -ErrorAction Continue
    exit 1
}
