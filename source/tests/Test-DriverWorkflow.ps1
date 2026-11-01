# Portable control-flow tests. Windows services, PnP and reboot are deliberately mocked.
# These tests do NOT constitute Windows installation or hardware validation.
param([Parameter(Mandatory=$true)][string]$SourceRoot)
$ErrorActionPreference='Stop'
$global:OpenDeployTestscenario=''
$global:OpenDeployTestrebooted=$false
$global:OpenDeployTestregistered=$false
function global:New-ScheduledTaskAction { param($Execute,$Argument) [pscustomobject]@{Execute=$Execute;Argument=$Argument} }
function global:New-ScheduledTaskTrigger { param([switch]$AtStartup) 'trigger' }
function global:New-ScheduledTaskPrincipal { param($UserId,$LogonType,$RunLevel) 'principal' }
function global:New-ScheduledTaskSettingsSet { param([switch]$StartWhenAvailable,[switch]$AllowStartIfOnBatteries,[switch]$DontStopIfGoingOnBatteries,$ExecutionTimeLimit) 'settings' }
function global:Register-ScheduledTask { param($TaskName,$Action,$Trigger,$Principal,$Settings,[switch]$Force) $global:OpenDeployTestregistered=$true }
function global:Unregister-ScheduledTask { param($TaskName,[switch]$Confirm,$ErrorAction) $global:OpenDeployTestregistered=$false }
function global:Restart-Computer { param([switch]$Force) $global:OpenDeployTestrebooted=$true }
function global:pnputil.exe { $global:LASTEXITCODE=0; if($global:OpenDeployTestscenario -eq 'reboot'){$global:LASTEXITCODE=3010} }
function global:Get-CimInstance {
 param($ClassName,$ErrorAction)
 if($global:OpenDeployTestscenario -eq 'empty'){return}
 if($global:OpenDeployTestscenario -eq 'incomplete'){[pscustomobject]@{Name='Missing device';PNPDeviceID='TEST';ConfigManagerErrorCode=28}}else{[pscustomobject]@{Name='Healthy device';PNPDeviceID='TEST';ConfigManagerErrorCode=0}}
}
function global:Set-ItemProperty { param($Path,$Name,$Value) }
function global:Remove-ItemProperty { param($Path,$Name,$ErrorAction) }
function global:Test-Path {
 param([string]$Path)
 if($Path.StartsWith('HKLM:')){return $false}
 Microsoft.PowerShell.Management\Test-Path -LiteralPath $Path
}
function New-Fixture {
 $root=Join-Path ([IO.Path]::GetTempPath()) ('opendeploy-test-'+[guid]::NewGuid())
 New-Item $root -ItemType Directory|Out-Null
 Copy-Item (Join-Path $SourceRoot 'scripts') $root -Recurse
 New-Item (Join-Path $root 'bootstrap-drivers') -ItemType Directory|Out-Null
 $driver=Join-Path $root 'bootstrap-drivers/test.inf'
 Set-Content $driver 'fixture'
 @{Files=@(@{Path='bootstrap-drivers/test.inf';Size=(Get-Item $driver).Length;SHA256=(Get-FileHash $driver).Hash})}|ConvertTo-Json -Depth 4|Set-Content (Join-Path $root 'drivers-manifest.json')
 Set-Content (Join-Path $root 'plan.json') '{}'
 $planHash=(Get-FileHash (Join-Path $root 'plan.json')).Hash.ToLowerInvariant()
 @{plan_sha256=$planHash;phase='drivers'}|ConvertTo-Json|Set-Content (Join-Path $root 'flow-state.json')
 @{PlanSHA256=$planHash}|ConvertTo-Json|Set-Content (Join-Path $root 'deployment-complete.json')
 $planExe=Join-Path $root 'OpenDeploy.exe'
 [IO.File]::WriteAllText($planExe,"#!/bin/sh`necho validated`nexit 0`n"); & chmod +x $planExe
 New-Item (Join-Path $root 'vendor/sdio/scripts') -ItemType Directory -Force|Out-Null
 $exe=Join-Path $root 'vendor/sdio/SDIO_x64_R887.exe'
 [IO.File]::WriteAllText($exe,"#!/bin/sh`nexit 0`n")
 & chmod +x $exe
 return $root
}
$env:SystemDrive='C:'
$env:SystemRoot='/windows'
$env:ProgramData=Join-Path ([IO.Path]::GetTempPath()) 'opendeploy-test-programdata'
foreach($case in @('success','incomplete','empty','corrupt','no-handoff','reboot')) {
 $global:OpenDeployTestscenario=$case;$global:OpenDeployTestregistered=$false;$global:OpenDeployTestrebooted=$false
 $root=New-Fixture
 if($case -eq 'corrupt'){Add-Content (Join-Path $root 'bootstrap-drivers/test.inf') 'corrupt'}
 if($case -eq 'no-handoff'){Remove-Item (Join-Path $root 'deployment-complete.json')}
 try {
  $failed=$false
  try{& (Join-Path $root 'scripts/Install-Drivers.ps1') -Root $root}catch{$failed=$true}
  $complete=Microsoft.PowerShell.Management\Test-Path (Join-Path $root 'drivers-complete.json')
  switch($case) {
   'success' {if($failed -or !$complete -or $global:OpenDeployTestregistered){throw 'Success path did not complete and remove resume task'}}
   {$_ -in @('incomplete','empty','corrupt','no-handoff')} {if(!$failed -or $complete -or $global:OpenDeployTestregistered){throw 'Incomplete devices falsely marked complete'}}
   'reboot' {if($failed -or $complete -or !$global:OpenDeployTestrebooted -or !$global:OpenDeployTestregistered){throw 'Reboot path lost pending state/task'}}
  }
  Write-Output "PASS driver workflow: $case"
  if($case -eq 'reboot') {
   $global:OpenDeployTestscenario='success'
   & (Join-Path $root 'scripts/Install-Drivers.ps1') -Root $root -Resume
   if(!(Microsoft.PowerShell.Management\Test-Path (Join-Path $root 'drivers-complete.json')) -or $global:OpenDeployTestregistered){throw 'Automatic resume did not complete'}
   $state=Get-Content (Join-Path $root 'driver-state.json') -Raw|ConvertFrom-Json
   if($state.Attempt -ne 2){throw 'Resume lost attempt state'}
   Write-Output 'PASS driver workflow: automatic resume after reboot'
  }
 }finally{Remove-Item $root -Recurse -Force}
}
