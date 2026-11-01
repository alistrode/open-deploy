param([Parameter(Mandatory=$true)][string]$Root, [switch]$Resume)
. (Join-Path $PSScriptRoot 'Common.ps1')
$planHash = Assert-ConfiguredOperation $Root 'drivers'
$taskName = 'OpenDeploy-DriverResume'
$statePath = Join-Path $Root 'driver-state.json'
$completePath = Join-Path $Root 'drivers-complete.json'
$mutex = New-Object Threading.Mutex($false, 'Global\OpenDeploy-DriverInstall')
if (!$mutex.WaitOne(0)) { throw 'Driver installation is already running' }
try {
    if ($env:SystemDrive -eq 'X:' -or !(Test-Path (Join-Path $Root 'deployment-complete.json'))) { throw 'Driver installation requires an OpenDeploy-installed Windows' }
    if (Test-Path $completePath) {
        $existingProof=Get-Content $completePath -Raw | ConvertFrom-Json
        if ($existingProof.PlanSHA256 -cne $planHash) { throw 'Stale driver proof from another plan' }
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        return
    }
    Assert-DriverPayload $Root
    $state = @{Attempt=0; Status='starting'}
    if (Test-Path $statePath) {
        $old = Get-Content $statePath -Raw | ConvertFrom-Json
        $state.Attempt = [int]$old.Attempt
    }
    # Resume only after the user has activated the third stage. Never install
    # drivers merely because the new system has logged in for the first time.
    if ($Resume -and !(Test-Path $statePath)) { throw 'No user-started driver operation to resume' }
    if (!$Resume) { $state.Attempt = 0 }
    $state.Attempt++
    if ($state.Attempt -gt 3) { throw 'Automatic driver recovery exhausted; inspect evidence/driver-errors.log' }
    $state.Status = 'installing'
    Write-State $statePath $state
    New-Item (Join-Path $Root 'evidence') -ItemType Directory -Force | Out-Null
    Start-Transcript (Join-Path $Root 'evidence\driver-worker.log') -Append | Out-Null
    $action = New-ScheduledTaskAction -Execute (Join-Path $Root 'OpenDeploy.exe') -Argument ('--run --stage=drivers --resume --plan "' + (Join-Path $Root 'plan.json') + '"')
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    $bootstrap = Join-Path $Root 'bootstrap-drivers'
    # PnP selects compatible signed packages; do not force-install unmatched INFs.
    Invoke-Checked 'pnputil.exe' @('/add-driver',(Join-Path $bootstrap '*.inf'),'/subdirs','/install') @(0,3010)
    $needsRestart = $LASTEXITCODE -eq 3010
    if ($needsRestart -and $state.Attempt -lt 3) {
        $state.Status = 'reboot-pending'; Write-State $statePath $state
        Stop-Transcript | Out-Null
        Restart-Computer -Force
        return
    }
    $inventory = @(Get-CimInstance Win32_PnPEntity -ErrorAction Stop)
    if ($inventory.Count -eq 0) { throw 'Device inventory is empty; cannot certify driver installation' }
    $badBefore = @($inventory | Where-Object {$null -eq $_.ConfigManagerErrorCode -or $_.ConfigManagerErrorCode -ne 0})
    if ($badBefore.Count -gt 0) {
        $sdio = Join-Path $Root 'vendor\sdio'
        $script = Join-Path $sdio 'scripts\opendeploy-live.txt'
        @('verbose 384','logdir logs','logging on','enableinstall on','drpdir drivers','indexdir indexes\SDI','extractdir temp','init','checkupdates','onerror goto :offline','get indexes','onerror goto :offline','init',':offline','select missing','install','writedevicelist logs\devices-after.txt','reboot ifneeded','end') | Set-Content $script -Encoding ASCII
        # SDIO's documented install command fetches selected missing packages after
        # checkupdates. Keep these in drivers/ for the next run rather than clear them.
        Push-Location $sdio
        try { Invoke-Checked (Join-Path $sdio 'SDIO_x64_R887.exe') @("-script:$script",'-nogui') @(0,3010); $needsRestart = $needsRestart -or $LASTEXITCODE -eq 3010 } finally { Pop-Location }
    }
    $inventory = @(Get-CimInstance Win32_PnPEntity -ErrorAction Stop)
    if ($inventory.Count -eq 0) { throw 'Final device inventory is empty' }
    $bad = @($inventory | Where-Object {$null -eq $_.ConfigManagerErrorCode -or $_.ConfigManagerErrorCode -ne 0})
    Write-State (Join-Path $Root 'evidence\device-health.json') @($bad | Select-Object Name,PNPDeviceID,ConfigManagerErrorCode)
    $pending = $needsRestart -or (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') -or (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or (@($bad | Where-Object ConfigManagerErrorCode -eq 14).Count -gt 0)
    if ($pending -and $state.Attempt -lt 3) {
        $state.Status = 'reboot-pending'; Write-State $statePath $state
        Stop-Transcript | Out-Null
        Restart-Computer -Force
        return
    }
    if ($bad.Count -gt 0 -or $pending) { throw 'Drivers are incomplete or still require restart; inspect evidence/device-health.json' }
    $winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    Set-ItemProperty $winlogon 'AutoAdminLogon' '0'
    Remove-ItemProperty $winlogon 'DefaultPassword' -ErrorAction SilentlyContinue
    Write-State $completePath @{PlanSHA256=$planHash; CompletedAt=(Get-Date).ToString('o'); Attempts=$state.Attempt; DeviceProblems=0}
    $state.Status = 'complete';Write-State $statePath $state
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Startup\OpenDeploy-Drivers.cmd') -ErrorAction SilentlyContinue
    Write-Output 'Driver installation and device checks completed'
} catch {
    New-Item (Join-Path $Root 'evidence') -ItemType Directory -Force | Out-Null
    $_ | Out-String | Add-Content (Join-Path $Root 'evidence\driver-errors.log')
    Write-State $statePath @{Attempt=3; Status='failed'}
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    throw
} finally {
    try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch {}
    $mutex.ReleaseMutex(); $mutex.Dispose()
}
