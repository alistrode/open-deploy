param(
    [Parameter(Mandatory)][string]$EncryptedFile,
    [Parameter(Mandatory)][string]$KeyFile,
    [Parameter(Mandatory)][string]$OutputFile
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $OutputFile) { throw 'Output already exists; choose a new file' }
$key = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $KeyFile))
if ($key.Length -ne 32) { throw 'Expected the separately retained 32-byte original key' }
$input = [IO.File]::OpenRead((Resolve-Path -LiteralPath $EncryptedFile))
$aes = [Security.Cryptography.Aes]::Create()
$output = $null
try {
    $header = New-Object byte[] 32
    if ($input.Read($header,0,32) -ne 32 -or [Text.Encoding]::ASCII.GetString($header,0,8) -ne "ODISO1`r`n") { throw 'Unexpected original ISO container' }
    $length = [BitConverter]::ToInt64($header,8)
    $iv = New-Object byte[] 16
    [Array]::Copy($header,16,$iv,0,16)
    $aes.Key = $key; $aes.IV = $iv
    $crypto = New-Object Security.Cryptography.CryptoStream($input,$aes.CreateDecryptor(),[Security.Cryptography.CryptoStreamMode]::Read)
    $output = [IO.File]::Create($OutputFile)
    try { $crypto.CopyTo($output,8388608) } finally { $crypto.Dispose(); $output.Dispose(); $output=$null }
    if ((Get-Item -LiteralPath $OutputFile).Length -ne $length) { throw 'Restored original size differs' }
} finally { if($output){$output.Dispose()};$input.Dispose();$aes.Dispose() }
Write-Host 'Original prepared media restored. It retains the original private plan and target binding.'
