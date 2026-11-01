param(
    [string]$ExpectedComputerName = 'OPENDEPLOY-SSH',
    [string]$Destination = 'C:\OpenDeploy\SSHRelay'
)
$ErrorActionPreference = 'Stop'
$report = 'C:\OpenDeploy\ssh-bootstrap-result.json'
$computer = Get-CimInstance Win32_ComputerSystem
if ($env:COMPUTERNAME -ine $ExpectedComputerName -or $computer.Model -notmatch 'VirtualBox') {
    throw 'This bootstrap is restricted to the designated VirtualBox test guest.'
}
try {
    $source = Join-Path $PSScriptRoot 'SSHRelay'
    foreach ($required in @('runtime\node.exe', 'app\start.cjs', 'data\remote.json', 'data\host_key', 'data\connection-private.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $source $required))) {
            throw "Missing payload file: $required"
        }
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $Destination -Recurse -Force
    Get-ChildItem -LiteralPath $Destination -Recurse -File -Force | ForEach-Object { $_.IsReadOnly = $false }
    Set-TimeZone -Id 'UTC'
    [TimeZoneInfo]::ClearCachedData()
    $clockSync = 'not-synchronized'
    try {
        # The relay rejects stale signed frames. Correct a local-RTC/UTC setup
        # mismatch before starting it, using a fresh TLS-verified server date.
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $request = [Net.HttpWebRequest]::Create('https://www.microsoft.com/?opendeploy-clock=' + [guid]::NewGuid().ToString('N'))
        $request.Method = 'HEAD'
        $request.Timeout = 15000
        $request.Headers['Cache-Control'] = 'no-cache'
        $response = $request.GetResponse()
        try {
            $serverTime = [DateTimeOffset]::Parse($response.Headers['Date'], [Globalization.CultureInfo]::InvariantCulture)
        } finally { $response.Dispose() }
        if ([math]::Abs(([DateTime]::UtcNow - $serverTime.UtcDateTime).TotalSeconds) -gt 60) {
            Set-Date -Date $serverTime.LocalDateTime | Out-Null
            $clockSync = 'corrected-from-https-date'
        } else { $clockSync = 'already-within-60-seconds' }
    } catch {
        # Keep the payload installed even if the time endpoint is unavailable.
        # The controller still requires an actual authenticated SSH connection.
        $clockSync = 'https-date-unavailable'
    }
    $userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe (Join-Path $Destination 'data') /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "*$($userSid):(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not protect guest SSH credentials.' }
    $taskFile = Join-Path $Destination 'SSHRelay-task.xml'
    $taskDefinition = [IO.File]::ReadAllText($taskFile).Replace('encoding="UTF-8"', 'encoding="UTF-16"')
    [IO.File]::WriteAllText($taskFile, $taskDefinition, [Text.Encoding]::Unicode)
    & schtasks.exe /Create /TN 'OpenDeploy-SSHRelay' /XML $taskFile /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not register the guest startup task.' }
    & schtasks.exe /Run /TN 'OpenDeploy-SSHRelay' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not start the guest SSH task.' }
    [pscustomobject]@{
        Installed = $true
        ComputerName = $env:COMPUTERNAME
        Destination = $Destination
        StartupTask = 'OpenDeploy-SSHRelay'
        TaskAccount = 'SYSTEM'
        ClockSync = $clockSync
        WiFiDriverPackIncluded = $false
        RelayScriptSHA256 = (Get-FileHash (Join-Path $Destination 'app\start.cjs') -Algorithm SHA256).Hash.ToLower()
        InstalledAt = (Get-Date).ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $report -Encoding UTF8
} catch {
    New-Item -ItemType Directory -Path (Split-Path $report) -Force | Out-Null
    [pscustomobject]@{ Installed = $false; Error = $_.Exception.Message } | ConvertTo-Json | Set-Content -LiteralPath $report -Encoding UTF8
    throw
}
