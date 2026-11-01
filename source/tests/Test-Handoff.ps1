# Portable simulation: no disk/driver commands are executed.
param([Parameter(Mandatory=$true)][string]$SourceRoot)
$ErrorActionPreference='Stop'
if(Get-PSDrive C -ErrorAction SilentlyContinue){throw 'This isolated simulation requires no existing C: drive'}
$global:OpenDeployTestInjected=$false
function global:Get-Partition { param($DriveLetter,$ErrorAction) [pscustomobject]@{DiskNumber=42} }
function global:Add-WindowsDriver { param($Path,$Driver,[switch]$Recurse,$ErrorAction) $global:OpenDeployTestInjected=$true }
function global:robocopy.exe { param($From,$To) Copy-Item (Join-Path $From '*') $To -Recurse -Force; $global:LASTEXITCODE=1 }
$base=Join-Path ([IO.Path]::GetTempPath()) ('opendeploy-handoff-'+[guid]::NewGuid())
$runtime=Join-Path $base 'runtime';$target=Join-Path $base 'target'
New-Item $runtime,$target -ItemType Directory -Force|Out-Null
New-PSDrive -Name C -PSProvider FileSystem -Root $target|Out-Null
try{
 Copy-Item (Join-Path $SourceRoot 'scripts') $runtime -Recurse
 New-Item (Join-Path $runtime 'bootstrap-drivers') -ItemType Directory|Out-Null
 $inf=Join-Path $runtime 'bootstrap-drivers/test.inf';Set-Content $inf 'fixture'
 @{Files=@(@{Path='bootstrap-drivers/test.inf';Size=(Get-Item $inf).Length;SHA256=(Get-FileHash $inf).Hash})}|ConvertTo-Json -Depth 4|Set-Content (Join-Path $runtime 'drivers-manifest.json')
 Set-Content (Join-Path $runtime 'unattend.xml') '<unattend />'
 Set-Content (Join-Path $runtime 'plan.json') '{}'
 $planHash=(Get-FileHash (Join-Path $runtime 'plan.json')).Hash.ToLowerInvariant()
 @{plan_sha256=$planHash;phase='installing'}|ConvertTo-Json|Set-Content (Join-Path $runtime 'flow-state.json')
 $mock=Join-Path $runtime 'OpenDeploy.exe'
 $mockBody=@'
#!/bin/sh
if [ "$1" = "--checkpoint=installed" ]; then
 python -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["phase"]="installed"; json.dump(d,open(p,"w"))' "$(dirname "$0")/flow-state.json"
else
 echo validated
fi
exit 0
'@
 [IO.File]::WriteAllText($mock,$mockBody);& chmod +x $mock
 New-Item 'C:\Windows\System32' -ItemType Directory -Force|Out-Null
 Set-Content 'C:\Windows\System32\ntoskrnl.exe' 'fixture'
 $env:OPENDEPLOY_MEDIA_ID='simulation';$env:OPENDEPLOY_OS_IMAGE_INDEX='2'
 $failed=$false
 try{& (Join-Path $runtime 'scripts/Install-Handoff.ps1') -RuntimeRoot $runtime -DiskNumber 99}catch{$failed=$true}
 if(!$failed -or $global:OpenDeployTestInjected -or (Test-Path 'C:\OpenDeploy\deployment-complete.json')){throw 'Wrong target volume was accepted'}
 Write-Output 'PASS handoff: rejects wrong target before injection/copy'
 & (Join-Path $runtime 'scripts/Install-Handoff.ps1') -RuntimeRoot $runtime -DiskNumber 42
 foreach($path in @('C:\OpenDeploy\deployment-complete.json','C:\OpenDeploy\drivers-manifest.json','C:\Windows\Panther\unattend.xml','C:\Users\Public\Desktop\3-Install-Drivers.cmd')) {
  if(!(Test-Path $path)){throw "Missing handoff result: $path"}
 }
 if(!$global:OpenDeployTestInjected){throw 'Offline drivers were not injected'}
 Write-Output 'PASS handoff: offline drivers, copied runtime, unattended setup, headless stage entry and committed completion proof'
}finally{Remove-PSDrive C;Remove-Item $base -Recurse -Force}
