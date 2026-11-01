import pathlib,subprocess,os,struct,gzip,hashlib,json
import argparse
ap=argparse.ArgumentParser(description='Build pinned GRUB BIOS/UEFI boot files, without any installer ISO')
ap.add_argument('--grub-root',type=pathlib.Path,required=True)
ap.add_argument('--output',type=pathlib.Path,required=True)
ap.add_argument('--disk-bytes',type=int,default=2013265920)
args=ap.parse_args()
root=args.grub_root.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
env={**os.environ,'LD_LIBRARY_PATH':str(root/'usr/lib/x86_64-linux-gnu')}
early=out/'early.cfg';early.write_text('search --no-floppy --file --set=root /OpenDeploy-USB.marker\nset prefix=($root)/boot/grub\nconfigfile ($root)/boot/grub/grub.cfg\n')
mods='part_gpt part_msdos fat ntfs iso9660 loopback normal configfile search search_fs_file search_fs_uuid linux newc echo sleep test reboot halt'.split()
def run(args):subprocess.run([str(x) for x in args],env=env,check=True)
run([root/'usr/bin/grub-mkstandalone','-O','x86_64-efi','-d',root/'usr/lib/grub/x86_64-efi','-o',out/'BOOTX64.EFI','--locales=','--fonts=','--modules='+' '.join(mods),'boot/grub/grub.cfg='+str(early)])
bios=out/'bios';bios.mkdir(exist_ok=True)
(bios/'boot.img').write_bytes((root/'usr/lib/grub/i386-pc/boot.img').read_bytes())
run([root/'usr/bin/grub-mkimage','-O','i386-pc','-d',root/'usr/lib/grub/i386-pc','-p','/boot/grub','-c',early,'-o',bios/'core.img','biosdisk',*mods])
size=args.disk_bytes;start=2048;sectors=size//512-start
assert size%512==0 and size>=512*1024*1024
image=out/'usb-layout.img'
with image.open('wb') as f:f.truncate(size)
mbr=bytearray(512);mbr[446:462]=struct.pack('<B3sB3sII',0x80,b'\xfe\xff\xff',0x0c,b'\xfe\xff\xff',start,sectors);mbr[510:]=b'\x55\xaa'
with image.open('r+b') as f:f.write(mbr)
run([root/'usr/bin/mformat','-i',str(image)+'@@1048576','-T',str(sectors),'-F','-v','OD_PXVIRT','::'])
for p in ['::/EFI','::/EFI/BOOT','::/boot','::/boot/grub']:
 run([root/'usr/bin/mmd','-i',str(image)+'@@1048576',p])
marker=out/'OpenDeploy-USB.marker';marker.write_text('OpenDeploy hard-disk ISO boot\n')
run([root/'usr/bin/mcopy','-i',str(image)+'@@1048576',marker,'::/OpenDeploy-USB.marker'])
run([root/'usr/bin/mcopy','-i',str(image)+'@@1048576',out/'BOOTX64.EFI','::/EFI/BOOT/BOOTX64.EFI'])
(out/'device.map').write_text('(hd0) '+str(image)+'\n')
# Embed the contiguous core in the 1 MiB post-MBR gap. These are GRUB's
# i386-pc boot.h/setup.c offsets; no filesystem blocklists are used.
core=bytearray((bios/'core.img').read_bytes())
count=(len(core)+511)//512
assert count<2047
core.extend(b'\0'*(count*512-len(core)))
core[488:500]=b'\0'*12
struct.pack_into('<QHH',core,500,2,count-1,0x820)
boot=bytearray((bios/'boot.img').read_bytes())
struct.pack_into('<Q',boot,0x5c,1)
boot[0x64]=0xff
boot[0x66:0x68]=b'\x90\x90'
boot[440:]=mbr[440:]
with image.open('r+b') as f:
 f.write(boot);f.seek(512);f.write(core)
with image.open('rb') as f:prefix=f.read(32*1024*1024)
(out/'usb-prefix.img.gz').write_bytes(gzip.compress(prefix,compresslevel=9,mtime=0))
(out/'boot-manifest.json').write_text(json.dumps({'disk_bytes':size,'prefix_bytes':len(prefix),'partition_start':1048576,'filesystem':'FAT32','bios_core_sectors':count,'efi_bytes':(out/'BOOTX64.EFI').stat().st_size,'sha256':hashlib.sha256(prefix).hexdigest(),'grub_version':'2.12-9+deb13u2'},indent=2))
print('BUILT',image)
