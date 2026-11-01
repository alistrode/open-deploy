$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root='I:\xxm\PXVIRT-Trial-20261021\dev\Delivery-20261027'
$private=Join-Path $root 'private-export'
$key=[IO.File]::ReadAllBytes((Join-Path $root 'private-key\original-iso.key'))
function Seal-File([string]$SourcePath,[string]$TargetPath) {
 $a=[Security.Cryptography.Aes]::Create();$a.Key=$key;$a.GenerateIV()
 $s=[IO.File]::OpenRead($SourcePath);$o=[IO.File]::Create($TargetPath)
 try {
  $m=[Text.Encoding]::ASCII.GetBytes("ODISO1`r`n");$o.Write($m,0,8)
  $n=[BitConverter]::GetBytes([long]$s.Length);$o.Write($n,0,8);$o.Write($a.IV,0,16)
  $c=New-Object Security.Cryptography.CryptoStream($o,$a.CreateEncryptor(),[Security.Cryptography.CryptoStreamMode]::Write)
  try{$s.CopyTo($c,8388608);$c.FlushFinalBlock()}finally{$c.Dispose()}
 } finally {$s.Dispose();$o.Dispose();$a.Dispose()}
}
$corrected=Join-Path $private 'OpenDeploy-PXVIRT-Original-20261025.iso.aes.exact'
Seal-File (Join-Path $private 'OpenDeploy-PXVIRT-Original-20261025.iso') $corrected
Move-Item -LiteralPath $corrected -Destination (Join-Path $private 'OpenDeploy-PXVIRT-Original-20261025.iso.aes') -Force
$public=Join-Path $root 'transport-public.xml'
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider
$rsa.FromXmlString([IO.File]::ReadAllText($public))
$envelope=New-Object byte[] 96
[Array]::Copy($key,0,$envelope,0,32)
$s=[IO.File]::OpenRead((Join-Path $private 'OpenDeploy-PXVIRT-Original-20261025.iso.aes'))
try{[void]$s.Read($envelope,32,32)}finally{$s.Dispose()}
$s=[IO.File]::OpenRead((Join-Path $private 'OpenDeploy-Prepared-Media-32G-20261025.vdi.aes'))
try{[void]$s.Read($envelope,64,32)}finally{$s.Dispose()}
[IO.File]::WriteAllBytes((Join-Path $root 'transfer-parts\media-key-envelope.bin'),$rsa.Encrypt($envelope,$false))
$rsa.Dispose()
$aes=[Security.Cryptography.Aes]::Create();$aes.Key=$key;$aes.GenerateIV()
$src=[IO.File]::OpenRead((Join-Path $private 'prepared-media-delta.zip'))
$dst=[IO.File]::Create((Join-Path $root 'transfer-parts\prepared-media-delta.zip.aes'))
try{
 $magic=[Text.Encoding]::ASCII.GetBytes("ODISO1`r`n");$dst.Write($magic,0,8)
 $len=[BitConverter]::GetBytes([long]$src.Length);$dst.Write($len,0,8);$dst.Write($aes.IV,0,16)
 $stream=New-Object Security.Cryptography.CryptoStream($dst,$aes.CreateEncryptor(),[Security.Cryptography.CryptoStreamMode]::Write)
 try{$src.CopyTo($stream,8388608);$stream.FlushFinalBlock()}finally{$stream.Dispose()}
}finally{$src.Dispose();$dst.Dispose();$aes.Dispose()}
'Prepared-media differences sealed; original files unchanged'
