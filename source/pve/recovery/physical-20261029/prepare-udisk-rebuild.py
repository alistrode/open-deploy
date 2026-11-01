"""Preserve this OpenDeploy field job and assemble its actual v2 boot files.
Does not modify an installer ISO, identity, disk, firmware, or boot order.
"""
import datetime,gzip,hashlib,json,pathlib,shutil,struct,sys
JOB=pathlib.Path(r'C:\Windows\System32\config\systemprofile\AppData\Local\OpenDeploy\PXVIRT-harddisk-job')
BUNDLE=pathlib.Path(r'C:\Windows\Temp\OpenDeploy-HardDisk-USB\OpenDeploy')
OUT=pathlib.Path(r'E:\xxm\beifen\OpenDeploy\usb-rebuild-20261029')
if (OUT/'prepared.json').exists():
 print((OUT/'prepared.json').read_text());sys.exit(0)
OUT.mkdir(parents=True,exist_ok=True)
REC=JOB/'usb-recovery/20261029T114541Z'; V2=JOB/'install-logging/20261029T111315Z'
status=json.loads((REC/'capture-status.json').read_text(encoding='utf-8-sig'))
assert status['state']=='complete' and status['read_bytes']==2013265920 and status['error'] is None
raw=REC/'udisk-before.img.gz'; n=0
with gzip.open(raw,'rb') as f:
 while True:
  b=f.read(4*1024*1024)
  if not b:break
  n+=len(b)
assert n==2013265920
backup=OUT/'before';backup.mkdir(exist_ok=True)
for d in ['usb-tree','connection-identity','ai-private','install-logging','usb-recovery','split-boot']:
 shutil.copytree(JOB/d,backup/d,dirs_exist_ok=True)
for f in ['plan.json','state.json','installation-scope.json','harddisk-usb-receipt.json','preparation-ready.json']:
 if (JOB/f).exists():shutil.copy2(JOB/f,backup/f)
shutil.copytree(BUNDLE/'source/pve',backup/'application-source-pve',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(BUNDLE/'boot-assets',backup/'boot-assets',dirs_exist_ok=True)
stage=OUT/'staged-usb'
if stage.exists():raise RuntimeError('Partial staging exists; inspect it rather than merging blindly')
shutil.copytree(JOB/'usb-tree',stage)
# Recover the latest boot files, not the stale usb-tree boot menu.
for rel in ['EFI/BOOT/BOOTX64.EFI','BOOT/GRUB/GRUB.CFG','BOOT/opendeploy-install-logging.cpio.gz','OpenDeploy-USB.marker']:
 src=REC/'recovered-files'/rel
 dest=stage/({'BOOT/GRUB/GRUB.CFG':'boot/grub/grub.cfg','BOOT/opendeploy-install-logging.cpio.gz':'boot/opendeploy-install-logging.cpio.gz'}.get(rel,rel))
 dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
priv=stage/'OpenDeploy-private'
shutil.copytree(REC/'recovered-files/OpenDeploy-private',priv,dirs_exist_ok=True)
# v2's recovery point was only on C:; preserve it on the USB and E: now.
shutil.copytree(JOB/'install-logging',priv/'install-logging',dirs_exist_ok=True)
shutil.copytree(JOB/'connection-identity',priv/'connection-identity',dirs_exist_ok=True)
shutil.copytree(JOB/'ai-private',priv/'ai-private',dirs_exist_ok=True)
for name in ['plan.json','state.json','installation-scope.json']:
 (priv/'install-config').mkdir(exist_ok=True);shutil.copy2(JOB/name,priv/'install-config'/name)
identity=json.loads((JOB/'connection-identity/connection-private.json').read_text())
far=json.loads((stage/'opendeploy/relay-state/connection-private.json').read_text())
assert identity['fingerprint']==far['fingerprint'] and identity['session']==far['session']
assert (stage/'opendeploy/relay.tar.gz').stat().st_size==51667984
assert (stage/'EFI/BOOT/BOOTX64.EFI').stat().st_size==3661824
assert 'logged install v2 - direct PID1' in (stage/'boot/grub/grub.cfg').read_text()
# Read and compare the real newc overlay, including executable mode bits.
data=gzip.decompress((stage/'boot/opendeploy-install-logging.cpio.gz').read_bytes());pos=0;entries={}
while pos+110<=len(data):
 assert data[pos:pos+6] in [b'070701',b'070702']
 h=[int(data[pos+6+i*8:pos+14+i*8],16) for i in range(13)];mode=h[1];size=h[6];namesz=h[11]
 name=data[pos+110:pos+110+namesz-1].decode();pos=(pos+110+namesz+3)&~3
 content=data[pos:pos+size];pos=(pos+size+3)&~3
 if name=='TRAILER!!!':break
 entries[name.lstrip('./')]=(mode,content)
for arc,src in [('init','init.txt'),('opendeploy-original-init','opendeploy-original-init.txt'),('opendeploy-install-logged.sh','opendeploy-install-logged.sh.txt')]:
 mode,content=entries[arc];assert content==(V2/src).read_bytes() and mode&0o111
assert b'(while :; do sync; sleep 1; done)' not in entries['init'][1]
# Stage the pinned original layout. It already contains the UEFI bootstrap and FAT32 BPB.
prefix=gzip.decompress((BUNDLE/'boot-assets/usb-prefix.img.gz').read_bytes())
assert len(prefix)==33554432 and prefix[510:512]==b'\x55\xaa'
part=struct.unpack('<B3sB3sII',prefix[446:462]);assert part[2]==12 and part[4]==2048 and part[5]+2048==2013265920//512
assert prefix[1048576+82:1048576+90]==b'FAT32   '
(OUT/'usb-prefix.img').write_bytes(prefix)
files=[p for p in stage.rglob('*') if p.is_file()]
result={'prepared':True,'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'backup':str(backup),'staged_usb':str(stage),'files':len(files),'bytes':sum(p.stat().st_size for p in files),'full_original_image_bytes_verified':n,'v2_overlay_matches_recovery':True,'canonical_identity_preserved':True,'original_iso_changed':False,'disk_written':False,'rebooted':False}
(OUT/'prepared.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
