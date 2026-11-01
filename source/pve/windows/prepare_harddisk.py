"""Keep the original PXVIRT installer; export its ISO and a small boot USB tree."""
import argparse
import importlib.util
import json
import pathlib
import re
import shutil
import sys
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=pathlib.Path, required=True)
    parser.add_argument('--iso', type=pathlib.Path, required=True)
    parser.add_argument('--job', type=pathlib.Path, required=True)
    parser.add_argument('--usb-tree', type=pathlib.Path, required=True)
    parser.add_argument('--source-uuid', required=True)
    parser.add_argument('--disk-serial', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9A-Fa-f]{16}', args.source_uuid):
        raise ValueError('The exact NTFS volume serial (16 hex digits) is required')
    if not args.disk_serial.strip() or args.disk_serial == 'SELECT-IN-INSTALLER' or any(
            c in args.disk_serial for c in '*?[]\n\r'):
        raise ValueError('Configuration must contain an exact target disk serial')
    iso = args.iso.resolve()
    if iso.name != 'OpenDeploy-PXVIRT.iso' or iso.parent != pathlib.Path('E:/'):
        raise ValueError('This entry expects E:/OpenDeploy-PXVIRT.iso')
    source = args.bundle.resolve() / 'source/pve'
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location('original_opendeploy', source/'opendeploy.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    job = args.job.resolve()
    if not (job/'plan.json').exists():
        app.configure(argparse.Namespace(job=str(job), pxvirt=str(iso),
            relay=str(args.bundle.resolve()/'assets/linux-x64.tar.gz'),
            image_index=1, disk_serial=args.disk_serial, usb_device=None))
    plan = app.load(job/'plan.json')
    if plan.get('manual_install'):
        raise ValueError('Existing manual-install job is preserved; rewrite configuration separately')
    if args.disk_serial and plan['host']['disk_serial'] != args.disk_serial:
        raise ValueError('This job is bound to another target disk')
    with app.locked(job/'state.json'):
        app.prepare(job, plan, app.Journal(job/'state.json', plan))
    if not (job/'media/payload/media_payload.py').is_file():
        raise ValueError('Cached media predates identity-safe first boot; retain it and prepare with the later rewritten configuration')
    generated = job/'media/OpenDeploy-PXVIRT.iso'
    destination = args.usb_tree.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    # Export one complete prepared payload; never merge leftovers from an older export.
    shutil.rmtree(destination/'opendeploy', ignore_errors=True)
    shutil.copytree(job/'media/payload', destination/'opendeploy',
                    ignore=shutil.ignore_patterns('relay'))
    # Keep the pinned original relay archive compressed on the small USB; the
    # installed system expands it on its own disk during the same first boot.
    shutil.rmtree(destination/'opendeploy/relay', ignore_errors=True)
    shutil.copyfile(args.bundle.resolve()/'assets/linux-x64.tar.gz',
                    destination/'opendeploy/relay.tar.gz')
    # Original start.cjs requires this complete canonical pairing bundle.
    # Installation media is private; retain it rather than triggering new-key creation.
    shutil.copyfile(job/'connection-identity/connection-private.json',
                    destination/'opendeploy/relay-state/connection-private.json')
    boot = destination/'boot/grub'
    boot.mkdir(parents=True, exist_ok=True)
    parameter = ' proxmox-start-auto-installer'
    text = f'''set timeout=10
set default=0
insmod part_gpt
insmod part_msdos
insmod ntfs
insmod iso9660
insmod loopback
menuentry 'PXVIRT installation - image on hard disk' {{
    search --no-floppy --fs-uuid --set=isopart {args.source_uuid.upper()}
    if [ -z "$isopart" ]; then
        echo 'The configured source volume was not found.'
        sleep 15
    else
        set imagepath=/OpenDeploy-PXVIRT.iso
        loopback od ($isopart)$imagepath
        echo 'Loading the complete installation image into RAM. Keep the source disk connected.'
        linux (od)/boot/linux26 ro ramdisk_size=16777216 rw quiet splash=silent{parameter}
        initrd (od)/boot/initrd.img newc:pxvirt.iso:($isopart)$imagepath
    fi
}}
'''
    (boot/'grub.cfg').write_text(text, encoding='ascii', newline='\n')
    app.atomic(destination/'boot/source.json', {'schema':1, 'source_fs_uuid':args.source_uuid.upper(),
        'iso_path':'/OpenDeploy-PXVIRT.iso', 'plan_id':plan['id'],
        'manual_install':bool(plan.get('manual_install')), 'requires_complete_iso_in_ram':True})
    # The same pathname becomes the customized ISO only after preparation succeeds.
    if generated.exists():
        ready = iso.with_name(iso.name+'.ready')
        if ready.exists():
            raise ValueError('An earlier .ready file exists; inspect it before replacing anything')
        shutil.copyfile(generated, ready)
        with ready.open('r+b') as stream:
            os.fsync(stream.fileno())
        os.replace(ready, iso)
        receipt = json.loads((job/'media.json').read_text())
        receipt['outputs'] = [app.asset_record(iso, iso=True)]
        app.atomic(job/'media.json', receipt)
        generated.unlink()
    print(json.dumps({'iso':str(iso), 'iso_bytes':iso.stat().st_size,
        'usb_tree':str(destination), 'manual_install':bool(plan.get('manual_install')),
        'ai_private':str(job/'ai-private')}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
