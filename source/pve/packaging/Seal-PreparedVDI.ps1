$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = 'I:\xxm\PXVIRT-Trial-20261021\dev\Delivery-20261027'
$source = 'I:\xxm\PXVIRT-Trial-20261021\dev\vm\PXVIRT-Repo-Debug-20261022\Debug-Install-Media-32G.vdi'
$target = Join-Path $root 'private-export\OpenDeploy-Prepared-Media-32G-20261025.vdi.aes'
$key = [IO.File]::ReadAllBytes((Join-Path $root 'private-key\original-iso.key'))
if (Test-Path -LiteralPath $target) { throw 'Existing sealed prepared media retained' }
$aes = [Security.Cryptography.Aes]::Create(); $aes.Key = $key; $aes.GenerateIV()
$src = [IO.File]::OpenRead($source); $dst = [IO.File]::Create($target)
try {
    $header = [Text.Encoding]::ASCII.GetBytes("ODISO1`r`n")
    $dst.Write($header,0,8)
    $length = [BitConverter]::GetBytes([long]$src.Length); $dst.Write($length,0,8)
    $dst.Write($aes.IV,0,16)
    $crypto = New-Object Security.Cryptography.CryptoStream($dst,$aes.CreateEncryptor(),[Security.Cryptography.CryptoStreamMode]::Write)
    try { $src.CopyTo($crypto,8388608); $crypto.FlushFinalBlock() } finally {$crypto.Dispose()}
} finally {$src.Dispose();$dst.Dispose();$aes.Dispose()}
@{state='sealed';source_bytes=(Get-Item -LiteralPath $source).Length;encrypted_bytes=(Get-Item -LiteralPath $target).Length}|ConvertTo-Json
