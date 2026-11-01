"""Read-only RAM disk inventory. No installation, disk mounts or reboot."""
import argparse,datetime,gzip,json,os,pathlib,subprocess,sys,tempfile

def newc(name,data):
    name=name.encode()+b"\0"
    fields=[1,0o100755,0,0,1,0,len(data),0,0,0,0,len(name),0]
    result=b"070701"+b"".join(("%08x"%v).encode() for v in fields)+name
    result+=b"\0"*(-len(result)%4)
    result+=data
    return result+b"\0"*(-len(result)%4)

def main(job,bundle):
    job,bundle=pathlib.Path(job),pathlib.Path(bundle)
    sys.path.insert(0,str(bundle/"source/pve"))
    import opendeploy as app
    receipt=json.loads((job/"harddisk-usb-receipt.json").read_text(encoding="utf-8-sig"))
    probe=subprocess.run(["powershell.exe","-NoProfile","-Command",
        "$ErrorActionPreference='Stop';$d=Get-Partition -DriveLetter F|Get-Disk;"
        "@{id=[string]$d.UniqueId;size=[long]$d.Size;bus=[string]$d.BusType;"
        "boot=$d.IsBoot;system=$d.IsSystem}|ConvertTo-Json -Compress"],
        capture_output=True,text=True,check=True,timeout=30)
    disk=json.loads(probe.stdout)
    if (disk["id"]!=receipt["usb"]["unique_id"] or disk["size"]!=receipt["usb"]["size"]
            or disk["bus"]!="USB" or disk["boot"] or disk["system"]):
        raise ValueError("USB identity differs; nothing changed")
    cfg=pathlib.Path("F:/boot/grub/grub.cfg")
    old=cfg.read_bytes()
    if b"proxmox-start-auto-installer" not in old:
        raise ValueError("Expected restored original boot configuration")
    source=json.loads(pathlib.Path("F:/boot/source.json").read_text(encoding="utf-8-sig"))
    volume=source["source_fs_uuid"]
    if len(volume)!=16 or any(c not in "0123456789abcdefABCDEF" for c in volume):
        raise ValueError("Invalid volume serial")
    with tempfile.TemporaryDirectory(prefix="OpenDeploy-inventory-") as directory:
        initrd=pathlib.Path(directory)/"initrd.img"
        app.call(["xorriso","-osirrox","on","-indev","E:/OpenDeploy-PXVIRT.iso",
                  "-extract","/boot/initrd.img",str(initrd)])
        r=subprocess.run(["tar.exe","-xOf",str(initrd),"init"],capture_output=True,check=True)
        original=r.stdout.decode().replace("\r\n","\n")
    marker='if [ -n "$lvm2root" ]; then'
    if original.count(marker)!=1 or 'initrdisoimage="/pxvirt.iso"' not in original:
        raise ValueError("Unexpected init; nothing changed")
    collector=r'''
sleep 5
printf '\033[2J\033[H'
echo 'OPENDEPLOY RAM-ONLY DISK INVENTORY'
echo 'No installation. No disk mounted. Photograph this screen.'
echo 'Configured WWN: eui.00a0750139e164b9'
for dev in /sys/block/nvme* /sys/block/sd*; do
    [ -d "$dev" ] || continue
    echo '--------------------------------'
    echo "DEVICE: $dev"
    for item in size device/model device/serial wwid device/wwid; do
        if [ -f "$dev/$item" ]; then
            printf '%s: ' "$item"
            cat "$dev/$item"
        fi
    done
done
echo '--------------------------------'
echo 'STOPPED. No installation runs. Photograph device identifiers.'
while :; do sleep 3600; done
'''
    # Original driver loading, followed by inventory before ANY disk/ISO mount.
    init=(original.split(marker,1)[0]+collector).encode()
    overlay=gzip.compress(newc("init",init)+newc("TRAILER!!!",b""),mtime=0)
    target=pathlib.Path("F:/boot/opendeploy-inventory.cpio.gz")
    if target.exists():raise ValueError("Overlay exists; inspect before overwriting")
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup=job/"disk-inventory"/stamp
    backup.mkdir(parents=True,exist_ok=False)
    (backup/"grub.cfg.original").write_bytes(old)
    (backup/"init.inventory").write_bytes(init)
    config="""set timeout=10
set default=0
insmod part_gpt
insmod part_msdos
insmod ntfs
insmod iso9660
insmod loopback
function inventory_stop {
    echo 'Inventory boot failed. Photograph the error.'
    while [ 1 = 1 ]; do
        sleep 3600
    done
}
menuentry 'PXVIRT disk information only - NO INSTALLATION' {
    if search --no-floppy --file --set=usbpart /OpenDeploy-USB.marker; then
        echo '[1/3] Found USB'
    else
        inventory_stop
    fi
    if search --no-floppy --fs-uuid --set=isopart VOLUME_SERIAL; then
        echo '[2/3] Found source volume'
    else
        inventory_stop
    fi
    if loopback od ($isopart)/OpenDeploy-PXVIRT.iso; then
        echo 'Loading original Linux kernel'
    else
        inventory_stop
    fi
    if linux (od)/boot/linux26 ro panic=0 loglevel=4 console=tty0; then
        echo '[3/3] Loading small disk-inventory RAM image'
    else
        inventory_stop
    fi
    if initrd (od)/boot/initrd.img ($usbpart)/boot/opendeploy-inventory.cpio.gz; then
        boot
        inventory_stop
    else
        inventory_stop
    fi
}
""".replace("VOLUME_SERIAL",volume.upper()).encode("ascii")
    target.write_bytes(overlay)
    temporary=cfg.with_name("grub.cfg.inventory-new")
    with temporary.open("xb") as stream:
        stream.write(config);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,cfg)
    outcome={"inventory_prepared":True,"backup":str(backup),"overlay_bytes":len(overlay),
        "whole_iso_loaded_as_initramfs":False,"installation_started":False,
        "firmware_changed":False,"reboot_performed":False}
    (backup/"receipt.json").write_text(json.dumps(outcome,indent=2),encoding="utf-8")
    print(json.dumps(outcome))

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job",required=True);parser.add_argument("--bundle",required=True)
    args=parser.parse_args();main(args.job,args.bundle)
