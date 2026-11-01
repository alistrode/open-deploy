$ErrorActionPreference = 'Stop'
$Root = 'C:\OpenDeploy'
while ($true) {
    try {
        $state = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Setup\State').ImageState
        if ($state -eq 'IMAGE_STATE_COMPLETE' -and (Get-Service Schedule).Status -eq 'Running') {
            & (Join-Path $Root 'Guest-Finalize.ps1') -Bootstrap
            & (Join-Path $Root 'Guest-Finalize.ps1')
            if (Test-Path (Join-Path $Root 'ready.json')) { exit }
        }
    } catch {
        [IO.File]::AppendAllText((Join-Path $Root 'after-setup.log'), ([DateTime]::UtcNow.ToString('o') + ' ' + $_.Exception.Message + [Environment]::NewLine))
    }
    Start-Sleep -Seconds 15
}
