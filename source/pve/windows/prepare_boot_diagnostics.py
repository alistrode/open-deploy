"""Prepare a reversible, non-automatic PXVIRT boot diagnosis on the existing USB.

Does not rebuild the ISO, change firmware boot order, reboot, or start installation.
The original installer's proxdebug shell stops before launching the installer.
Do not exit that shell when collecting diagnostic output.
"""
import argparse
import datetime
import json
import os
import pathlib
import subprocess

def prepare(job):
    job = pathlib.Path(job).resolve()
    receipt = json.loads((job / "harddisk-usb-receipt.json").read_text(encoding="utf-8-sig"))
    if not receipt.get("completed"):
        raise ValueError("Existing completed media receipt required")
    # Match the physical USB from the existing preparation receipt.
    probe = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference='Stop';$d=Get-Partition -DriveLetter F | Get-Disk;"
         "$v=Get-Volume -DriveLetter F;"
         "@{id=[string]$d.UniqueId;size=[long]$d.Size;bus=[string]$d.BusType;"
         "boot=$d.IsBoot;system=$d.IsSystem;label=$v.FileSystemLabel}|ConvertTo-Json -Compress"],
        capture_output=True, text=True, check=True, timeout=30)
    disk = json.loads(probe.stdout)
    expected = receipt["usb"]
    if (disk["id"] != str(expected["unique_id"]) or disk["size"] != expected["size"]
            or disk["bus"] != "USB" or disk["boot"] or disk["system"]
            or disk["label"] != "OD_PXVIRT"):
        raise ValueError("Prepared USB identity differs; nothing changed")
    root = pathlib.Path("F:/")
    cfg = root / "boot/grub/grub.cfg"
    original = cfg.read_bytes()
    text = original.decode("ascii")
    if ("newc:pxvirt.iso:" not in text or "proxmox-start-auto-installer" not in text
            or "OpenDeploy-PXVIRT.iso" not in text):
        raise ValueError("Expected original automatic boot configuration; nothing changed")
    source = json.loads((root / "boot/source.json").read_text(encoding="utf-8-sig"))
    plan = json.loads((job / "plan.json").read_text(encoding="utf-8-sig"))
    if source["plan_id"] != plan["id"]:
        raise ValueError("USB and job plan differ; nothing changed")
    volume = source["source_fs_uuid"]
    if len(volume) != 16 or any(c not in "0123456789abcdefABCDEF" for c in volume):
        raise ValueError("Invalid source UUID")
    diagnostic = """set timeout=10
set default=0
insmod part_gpt
insmod part_msdos
insmod ntfs
insmod iso9660
insmod loopback
function od_stop {
    echo 'Stopped. Photograph the error above. Do not continue installation.'
    while [ 1 = 1 ]; do
        sleep 3600
    done
}
menuentry 'PXVIRT boot diagnosis - no automatic installation' {
    echo '[1/4] Finding the configured ISO volume'
    if search --no-floppy --fs-uuid --set=isopart UUID_VALUE; then
        set imagepath=/OpenDeploy-PXVIRT.iso
    else
        echo 'ERROR: source volume lookup failed'
        od_stop
    fi
    if loopback od ($isopart)$imagepath; then
        echo '[2/4] Loading Linux kernel'
    else
        echo 'ERROR: ISO loopback failed'
        od_stop
    fi
    if linux (od)/boot/linux26 ro ramdisk_size=16777216 rw proxdebug panic=0 loglevel=7 ignore_loglevel console=tty0; then
        echo '[3/4] Loading initial RAM disk and complete ISO. Please wait.'
    else
        echo 'ERROR: Linux kernel load failed'
        od_stop
    fi
    if initrd (od)/boot/initrd.img newc:pxvirt.iso:($isopart)$imagepath; then
        echo '[4/4] RAM loading completed. Starting Linux diagnostic mode.'
        echo 'Stop at the debug shell. Do not type exit or press Ctrl-D.'
        sleep 5
        boot
        echo 'ERROR: boot returned to GRUB'
        od_stop
    else
        echo 'ERROR: initial RAM disk or complete ISO load failed'
        od_stop
    fi
}
""".replace("UUID_VALUE", volume.upper())
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = job / "boot-diagnostics" / stamp
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "grub.cfg.original").write_bytes(original)
    (backup / "grub.cfg.diagnostic").write_text(diagnostic, encoding="ascii", newline="\n")
    temporary = cfg.with_name("grub.cfg.diagnostic-new")
    if temporary.exists():
        raise ValueError("Earlier temporary configuration exists; original preserved")
    with temporary.open("xb") as stream:
        stream.write(diagnostic.encode("ascii"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, cfg)
    result = {
        "diagnostic_boot_prepared": True, "backup": str(backup),
        "automatic_installation_parameter": False, "installer_debug_pause": True,
        "reboot_performed": False, "firmware_changed": False, "iso_changed": False,
        "restore": "Copy grub.cfg.original from the backup over F:/boot/grub/grub.cfg before explicitly authorized installation."
    }
    (backup / "receipt.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    prepare(args.job)
