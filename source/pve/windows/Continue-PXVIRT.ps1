param([string]$Job = (Join-Path $env:LOCALAPPDATA 'OpenDeploy\PXVIRT-job-v2'))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName Microsoft.VisualBasic
$address = [Microsoft.VisualBasic.Interaction]::InputBox('PXVIRT address / IP', 'OpenDeploy - Continue')
if (!$address) { exit }
$address = $address.Trim()
$hostAddress = $null
if ([Net.IPAddress]::TryParse($address, [ref]$hostAddress)) {
    if ($hostAddress.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetworkV6) { $address = '[' + $address + ']' }
} elseif ($address -notmatch '^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$') { throw 'Enter a host name or IP address' }
$access = Get-Content -LiteralPath (Join-Path $Job 'portal-access.json') -Raw | ConvertFrom-Json
Start-Process ('https://' + $address + ':' + [int]$access.port + '/#' + [Uri]::EscapeDataString([string]$access.token))
