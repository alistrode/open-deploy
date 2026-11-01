import subprocess,tempfile,pathlib
import shutil
root=pathlib.Path(__file__).resolve().parents[1]
pwsh=shutil.which('pwsh')
if not pwsh: raise SystemExit('PowerShell 7 (pwsh) is required for the mocked preflight checks')
entry=root/'windows/Start-VM.ps1'
base='''
function Get-CimInstance { [pscustomobject]@{ Model='MODEL' } }
function Get-Disk { @(
[pscustomobject]@{ Number=1; SerialNumber='target'; IsBoot=$false; IsSystem=$false; IsReadOnly=$false; IsOffline=$false; BusType='SATA' },
[pscustomobject]@{ Number=2; SerialNumber='media'; IsBoot=$false; IsSystem=$false; IsReadOnly=$false; IsOffline=$false; BusType='BUS' }
) }
& 'ENTRY' -Job '/tmp/vm-test' -SourceIso '/missing.iso' -TargetDiskSerial 'target' -MediaDiskSerial 'SERIAL'
exit $LASTEXITCODE
'''.replace('ENTRY',str(entry))
cases=[('host','Physical PC','SATA','media','requires a VirtualBox'),('same disk','VirtualBox','SATA','target','must be different'),('missing serial','VirtualBox','SATA','absent','exactly one disk'),('USB passthrough','VirtualBox','USB','media','dedicated virtual disks'),('missing ISO','VirtualBox','SATA','media','does not exist')]
for name,model,bus,serial,want in cases:
 with tempfile.NamedTemporaryFile(suffix='.ps1',mode='w') as f:
  f.write(base.replace('MODEL',model).replace('BUS',bus).replace('SERIAL',serial));f.flush()
  p=subprocess.run([str(pwsh),'-NoProfile','-File',f.name],capture_output=True,text=True)
  assert p.returncode==1 and want in p.stdout+p.stderr,(name,p.returncode,p.stdout,p.stderr)
 print('PASS',name)
