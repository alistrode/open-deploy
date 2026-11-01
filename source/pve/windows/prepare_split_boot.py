"""Prepare split-initramfs transport for the existing ISO, keeping installer code unchanged."""
import argparse,datetime,json,os,pathlib,shutil,subprocess,sys,tempfile,tomllib

def header(name,size,mode,index):
    n=name.encode()+b"\0"
    fields=[index,mode,0,0,1,0,size,0,0,0,0,len(n),0]
    h=b"070701"+b"".join(("%08x"%x).encode() for x in fields)+n
    return h+b"\0"*(-len(h)%4)
def small(out,name,data,index):
    out.write(header(name,len(data),0o100755,index));out.write(data);out.write(b"\0"*(-len(data)%4))
def main(job,bundle):
    job,bundle=pathlib.Path(job),pathlib.Path(bundle)
    sys.path.insert(0,str(bundle/'source/pve'));import opendeploy as app
    iso=pathlib.Path('E:/OpenDeploy-PXVIRT.iso')
    output=pathlib.Path('E:/OpenDeploy-PXVIRT.boot.cpio')
    pending=output.with_suffix('.cpio.partial')
    if output.exists() or pending.exists():raise RuntimeError('Existing boot payload; inspect before replacing')
    if shutil.disk_usage(iso.parent).free<iso.stat().st_size+100000000:raise RuntimeError('Insufficient payload space')
    receipt=json.loads((job/'harddisk-usb-receipt.json').read_text(encoding='utf-8-sig'))
    d=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',
      "$ErrorActionPreference='Stop';$d=Get-Partition -DriveLetter F|Get-Disk;@{id=[string]$d.UniqueId;size=[long]$d.Size;bus=[string]$d.BusType;boot=$d.IsBoot;system=$d.IsSystem}|ConvertTo-Json -Compress"],text=True))
    if d['id']!=receipt['usb']['unique_id'] or d['size']!=receipt['usb']['size'] or d['bus']!='USB' or d['boot'] or d['system']:raise RuntimeError('USB identity differs')
    plan=json.loads((pathlib.Path('F:/opendeploy')/'plan.json').read_text())
    if plan['host']['disk_serial']!='222339E164B9':raise RuntimeError('Unexpected target')
    with tempfile.TemporaryDirectory(prefix='OpenDeploy-split-') as temp:
        temp=pathlib.Path(temp)
        for source,name in [('/answer.toml','answer.toml'),('/boot/initrd.img','initrd.img')]:
            app.call(['xorriso','-osirrox','on','-indev',iso,'-extract',source,temp/name])
        if tomllib.loads((temp/'answer.toml').read_text())['disk-setup']['filter']!={'ID_SERIAL_SHORT':'222339E164B9'}:raise RuntimeError('Unexpected ISO filter')
        original=subprocess.check_output(['tar.exe','-xOf',str(temp/'initrd.img'),'init'])
        names=subprocess.check_output(['tar.exe','-tf',str(temp/'initrd.img')],text=True).splitlines()
        bb=next(('/'+n.removeprefix('./') for n in names if n.removeprefix('./') in ['bin/busybox','usr/bin/busybox']),None)
        if not bb or b'initrdisoimage="/pxvirt.iso"' not in original:raise RuntimeError('Unexpected initrd')
    size=iso.stat().st_size;limit=1024**3
    pieces=[min(limit,size-offset) for offset in range(0,size,limit)]
    paths=['/od-iso-%03d'%i for i in range(len(pieces))]
    wrapper=('#!/bin/sh\nPATH=/sbin:/bin:/usr/sbin:/usr/bin\nexport PATH\nBB='+bb+'\n'
      'stop_boot() { echo "OpenDeploy image assembly failed; installation stopped."; while :; do "$BB" sleep 3600; done; }\n'
      'echo "OpenDeploy: assembling complete ISO in RAM."\n'
      '"$BB" cat '+' '.join(paths)+' > /pxvirt.iso || stop_boot\n'
      'actual=$("$BB" wc -c < /pxvirt.iso)\n'
      '[ "$actual" = "'+str(size)+'" ] || stop_boot\n'
      '"$BB" rm -f '+' '.join(paths)+'\n'
      'echo "OpenDeploy: complete ISO ready. Starting original installer."\n'
      'exec /bin/sh /opendeploy-original-init\nstop_boot\n').encode()
    backup=job/'split-boot'/datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    backup.mkdir(parents=True)
    cfg=pathlib.Path('F:/boot/grub/grub.cfg')
    shutil.copy2(cfg,backup/'grub.cfg.previous')
    (backup/'init.wrapper').write_bytes(wrapper)
    with pending.open('xb') as out,iso.open('rb') as source:
        small(out,'init',wrapper,1);small(out,'opendeploy-original-init',original,2)
        for index,length in enumerate(pieces):
            out.write(header(paths[index][1:],length,0o100644,index+3))
            remain=length
            while remain:
                block=source.read(min(remain,4*1024**2))
                if not block:raise RuntimeError('Unexpected ISO EOF')
                out.write(block);remain-=len(block)
            out.write(b'\0'*(-length%4))
            print('PAYLOAD_PART',index,length,flush=True)
        small(out,'TRAILER!!!',b'',len(pieces)+3)
        out.flush();os.fsync(out.fileno())
    # Compare payload bytes directly against source; no ISO digest is calculated.
    with pending.open('rb') as stream,iso.open('rb') as source:
        seen=[]
        while True:
            h=stream.read(110)
            if h[:6]!=b'070701':raise RuntimeError('Invalid cpio header')
            length=int(h[54:62],16);nlen=int(h[94:102],16)
            name=stream.read(nlen)[:-1].decode();stream.read(-(110+nlen)%4)
            if name=='TRAILER!!!':break
            if name.startswith('od-iso-'):
                seen.append(name);remain=length
                if length>=2**31:raise RuntimeError('Part exceeds old-kernel limit')
                while remain:
                    count=min(remain,4*1024**2)
                    if stream.read(count)!=source.read(count):raise RuntimeError('Payload differs from ISO')
                    remain-=count
            else:stream.seek(length,1)
            stream.read(-length%4)
        if seen!=[p[1:] for p in paths] or source.read(1):raise RuntimeError('Incomplete payload')
    os.replace(pending,output)
    sourceinfo=json.loads(pathlib.Path('F:/boot/source.json').read_text(encoding='utf-8-sig'))
    uuid=sourceinfo['source_fs_uuid']
    if len(uuid)!=16 or any(c not in '0123456789abcdefABCDEF' for c in uuid):raise RuntimeError('Invalid source UUID')
    grub="""set timeout=10
set default=0
insmod part_gpt
insmod part_msdos
insmod ntfs
insmod iso9660
insmod loopback
function od_stop {
    echo 'Boot failed. Photograph this screen. Installation has not started.'
    while [ 1 = 1 ]; do
        sleep 3600
    done
}
menuentry 'PXVIRT automatic installation - Micron internal disk' {
    if search --no-floppy --fs-uuid --set=isopart SOURCE_UUID; then
        echo '[1/3] Found installation source'
    else
        od_stop
    fi
    if loopback od ($isopart)/OpenDeploy-PXVIRT.iso; then
        echo '[2/3] Loading Linux'
    else
        od_stop
    fi
    if linux (od)/boot/linux26 ro ramdisk_size=16777216 rw panic=0 proxmox-start-auto-installer; then
        echo '[3/3] Loading split ISO payload. Keep E and F connected.'
    else
        od_stop
    fi
    if initrd (od)/boot/initrd.img ($isopart)/OpenDeploy-PXVIRT.boot.cpio; then
        boot
        od_stop
    else
        od_stop
    fi
}
""".replace('SOURCE_UUID',uuid.upper()).encode()
    temporary=cfg.with_name('grub.cfg.split-new')
    with temporary.open('xb') as out:out.write(grub);out.flush();os.fsync(out.fileno())
    os.replace(temporary,cfg)
    if cfg.read_bytes()!=grub:raise RuntimeError('Boot config readback differs')
    result={'prepared':True,'source_iso_bytes':size,'payload_bytes':output.stat().st_size,
      'parts':pieces,'payload_byte_comparison':True,'target_serial':'222339E164B9',
      'backup':str(backup),'automatic_installation_entry':True,'reboot_performed':False,
      'physical_installation_verified':False}
    (backup/'receipt.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',required=True);p.add_argument('--bundle',required=True)
    args=p.parse_args();main(args.job,args.bundle)
