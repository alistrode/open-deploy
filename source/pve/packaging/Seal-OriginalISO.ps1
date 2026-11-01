param(
    [string]$Export = 'I:\xxm\PXVIRT-Trial-20261021\dev\Delivery-20261027\private-export',
    [string]$Private = 'I:\xxm\PXVIRT-Trial-20261021\dev\Delivery-20261027\private-key'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
New-Item -ItemType Directory -Path $Private -Force | Out-Null
& icacls.exe $Private /inheritance:r /grant:r 'Administrator:(OI)(CI)F' 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Private key ACL failed' }
$source = Join-Path $Export 'OpenDeploy-PXVIRT-Original-20261025.iso'
$target = $source + '.aes'
$keyPath = Join-Path $Private 'original-iso.key'
if ((Test-Path -LiteralPath $target) -or (Test-Path -LiteralPath $keyPath)) { throw 'Existing sealed original retained' }
$key = New-Object byte[] 32
$random = [Security.Cryptography.RandomNumberGenerator]::Create()
$random.GetBytes($key)
[IO.File]::WriteAllBytes($keyPath, $key)
$aes = [Security.Cryptography.Aes]::Create()
$aes.Key = $key
$aes.GenerateIV()
$input = [IO.File]::OpenRead($source)
$output = [IO.File]::Create($target)
try {
    $magic = [Text.Encoding]::ASCII.GetBytes("ODISO1`r`n")
    $output.Write($magic, 0, $magic.Length)
    $length = [BitConverter]::GetBytes([long]$input.Length)
    $output.Write($length, 0, $length.Length)
    $output.Write($aes.IV, 0, $aes.IV.Length)
    $crypto = New-Object Security.Cryptography.CryptoStream($output, $aes.CreateEncryptor(), [Security.Cryptography.CryptoStreamMode]::Write)
    try { $input.CopyTo($crypto, 8388608); $crypto.FlushFinalBlock() }
    finally { $crypto.Dispose() }
} finally { $input.Dispose(); $output.Dispose(); $aes.Dispose(); $random.Dispose() }
@{state='sealed';original_bytes=(Get-Item -LiteralPath $source).Length;encrypted_bytes=(Get-Item -LiteralPath $target).Length;key_path=$keyPath} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Export 'sealed-status.json') -Encoding UTF8
