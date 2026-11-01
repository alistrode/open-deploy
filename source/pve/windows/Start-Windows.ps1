param(
    [string]$TargetDiskSerial,
    [string]$UsbSerial,
    [switch]$Simulation,
    [switch]$RestartToMedia,
    [string]$HardDiskIso,
    [string]$SourceIso,
    [string]$UsbDriveLetter = 'F',
    [string]$PythonPath,
    [string]$Job = (Join-Path $env:LOCALAPPDATA 'OpenDeploy\PXVIRT-job-v2')
)
$ErrorActionPreference = 'Stop'
try {
    $Root = $PSScriptRoot
    if ($HardDiskIso) {
        if (!$PythonPath) { $PythonPath = Join-Path $Root 'python\python.exe' }
        & (Join-Path $Root 'source\pve\windows\Start-HardDisk-USB.ps1') -BundleRoot $Root `
            -Image $HardDiskIso -UsbDriveLetter $UsbDriveLetter -PythonPath $PythonPath `
            -TargetDiskSerial $TargetDiskSerial
        exit $LASTEXITCODE
    }
    $env:PATH = (Join-Path $Root 'runtime\usr\bin') + ';' + (Join-Path $Root 'wimlib') + ';' + $env:SystemRoot + '\System32'
    $env:MSYSTEM = 'MSYS'
    $env:CHERE_INVOKING = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $Python = Join-Path $Root 'python\python.exe'
    $Builder = Join-Path $Root 'source\pve\windows\build_windows.py'
    $env:OD_BUNDLE = $Root
    $env:OD_JOB = $Job
    $env:OD_DISK_SERIAL = $TargetDiskSerial
    if (!$TargetDiskSerial -or !$UsbSerial) {
        # Configure once; later double-clicks reuse private configuration.
        $configPath = Join-Path $Job 'windows-settings.json'
        if (!(Test-Path -LiteralPath $configPath)) {
            & (Join-Path $Root 'Configure-Windows.ps1') -Job $Job
        }
        $settings = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (!$TargetDiskSerial) { $env:OD_DISK_SERIAL = $TargetDiskSerial = [string]$settings.target_disk_serial }
        if (!$UsbSerial) { $UsbSerial = [string]$settings.usb_serial }
        if (!$PSBoundParameters.ContainsKey('Simulation')) { $Simulation = [bool]$settings.simulation }
    }
    if ($Simulation -and !$PSBoundParameters.ContainsKey('RestartToMedia')) { $RestartToMedia = $true }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (!(New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        function Quote-PS([string]$Value) { return "'" + $Value.Replace("'", "''") + "'" }
        $command = '& ' + (Quote-PS $PSCommandPath) + ' -TargetDiskSerial ' + (Quote-PS $TargetDiskSerial) + ' -UsbSerial ' + (Quote-PS $UsbSerial) + ' -Job ' + (Quote-PS $Job)
        if ($Simulation) { $command += ' -Simulation' }
        if ($SourceIso) { $command += ' -SourceIso ' + (Quote-PS $SourceIso) }
        $command += ' -RestartToMedia:$' + ([bool]$RestartToMedia).ToString().ToLowerInvariant()
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
        $child = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded) -Verb RunAs -Wait -PassThru
        exit $child.ExitCode
    }
    if ($RestartToMedia -and !$Simulation) { throw 'Automatic preparation-computer restart is restricted to simulation.' }
    if ($Simulation) {
        if ((Get-CimInstance Win32_ComputerSystem).Model -notmatch 'VirtualBox') { throw 'Simulation mode is restricted to a VirtualBox guest' }
        $policy = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
        New-Item -Path $policy -Force | Out-Null
        Set-ItemProperty -Path $policy -Name NoAutoUpdate -Value 1 -Type DWord
        if (Get-Service wuauserv -ErrorAction SilentlyContinue) {
            Stop-Service wuauserv -Force
            Set-Service wuauserv -StartupType Disabled
        }
    }
    $buildArgs = @($Builder, '--bundle', $Root, '--job', $Job, '--disk-serial', $TargetDiskSerial)
    if ($SourceIso) { $buildArgs += @('--iso', $SourceIso) }
    & $Python @buildArgs
    if ($LASTEXITCODE -ne 0) { throw 'ISO construction failed; existing job was retained for inspection.' }
    & (Join-Path $Root 'Write-Usb.ps1') -Image (Join-Path $Job 'media\OpenDeploy-PXVIRT.iso') -UsbSerial $UsbSerial -Receipt (Join-Path $Job 'windows-usb-receipt.json') -Simulation:$Simulation
    if ($RestartToMedia) {
        & (Join-Path $Root 'Boot-Media.ps1') -UsbSerial $UsbSerial -Job $Job -Restart
    }
    if ($RestartToMedia) {
        Write-Host 'PXVIRT installation media is ready. This simulation guest will restart into the installer in 20 seconds. Job:' $Job
    } else {
        Write-Host 'PXVIRT installation media is ready. Boot the target from it. After PXVIRT starts, use Continue-PXVIRT.cmd. Job:' $Job
    }
    exit 0
} catch {
    Write-Error -Message $_ -ErrorAction Continue
    exit 1
}

