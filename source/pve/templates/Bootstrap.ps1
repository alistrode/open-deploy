$ErrorActionPreference = 'Stop'
$plan = Get-Content (Join-Path $PSScriptRoot 'guest-plan.json') -Raw | ConvertFrom-Json
if ((Get-CimInstance Win32_ComputerSystemProduct).UUID -ine $plan.uuid) { throw 'Unexpected VM identity' }
$target = 'C:\OpenDeploy'
New-Item -ItemType Directory -Path $target -Force | Out-Null
if ($PSScriptRoot.TrimEnd('\') -ine $target) {
    Get-ChildItem -LiteralPath $PSScriptRoot -Force | Copy-Item -Destination $target -Recurse -Force
}
$setup = 'C:\Windows\Setup\Scripts'
New-Item -ItemType Directory -Path $setup -Force | Out-Null
$complete = Join-Path $setup 'SetupComplete.cmd'
$marker = 'REM OpenDeploy after-setup continuation'
$current = if (Test-Path -LiteralPath $complete) { [IO.File]::ReadAllText($complete) } else { '' }
if (!$current.Contains($marker)) {
    $previous = Join-Path $setup 'OpenDeploy-Previous-SetupComplete.cmd'
    if ($current) {
        if (Test-Path -LiteralPath $previous) { throw 'Previous SetupComplete continuation already exists' }
        [IO.File]::WriteAllText($previous, $current, [Text.Encoding]::Default)
    }
    $lines = @('@echo off', $marker)
    if ($current) { $lines += 'cmd.exe /d /c call "C:\Windows\Setup\Scripts\OpenDeploy-Previous-SetupComplete.cmd"' }
    $lines += 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -WindowStyle Hidden -ArgumentList ''-NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\OpenDeploy\After-Setup.ps1''"'
    $lines += 'exit /b 0'
    [IO.File]::WriteAllLines($complete, $lines, [Text.Encoding]::ASCII)
}
& (Join-Path $target 'Guest-Finalize.ps1') -Bootstrap
