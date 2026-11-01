#!/bin/bash
set -euo pipefail
umask 077
# Keep an already registered channel running even if media or host setup fails.
# start is idempotent: it does not restart or disconnect an active service.
keep_existing_connection() {
    if [ -f /etc/systemd/system/opendeploy-relay.service ]; then
        systemctl start --no-block opendeploy-relay.service || true
    fi
}
keep_existing_connection
trap keep_existing_connection ERR
expected='__PLAN_ID__'
mountpoint=$(mktemp -d /run/opendeploy-media.XXXXXX)
cleanup() { mountpoint -q "$mountpoint" && umount "$mountpoint" || true; rmdir "$mountpoint" || true; }
trap cleanup EXIT
found=0
while IFS= read -r device; do
    # Installation media can be the original ISO9660 device or the FAT USB
    # carrying only the boot loader and this plan's deployment payload.
    if mount -t auto -o ro "$device" "$mountpoint" 2>/dev/null; then
        if python3 - "$mountpoint/opendeploy/plan.json" "$expected" <<'PY'
import json,pathlib,sys
try:
    same=json.loads(pathlib.Path(sys.argv[1]).read_text())['id']==sys.argv[2]
except (OSError,ValueError,KeyError):
    same=False
sys.exit(0 if same else 1)
PY
        then
            found=1
            break
        fi
        umount "$mountpoint"
    fi
done < <(lsblk --list --paths --noheadings --output NAME,TYPE | awk '$2 == "disk" || $2 == "part" || $2 == "rom" {print $1}')
[ "$found" -eq 1 ] || { echo 'Keep this deployment installation medium connected.' >&2; exit 1; }
python3 "$mountpoint/opendeploy/media_payload.py" "$mountpoint/opendeploy" /opt/opendeploy
python3 - <<'PYBIND'
import json,pathlib,os
target=pathlib.Path('/opt/opendeploy')
# An interactive install lets the operator select its disk in the original
# installer. Bind once to that installed root, never choose a disk to erase here.
plan_path=target/'plan.json'
pending=target/'root-binding.json'
if pending.exists():
    transaction=json.loads(pending.read_text())
    for name,value in [('plan.json',transaction['plan']),('state.json',transaction['state'])]:
        destination=target/name;temporary=destination.with_name(destination.name+'.binding')
        temporary.write_text(json.dumps(value,indent=2)+'\n')
        os.replace(temporary,destination)
    pending.unlink()
plan=json.loads(plan_path.read_text())
if plan.get('manual_install') and plan['host']['disk_serial']=='SELECT-IN-INSTALLER':
    import subprocess,hashlib
    root=subprocess.check_output(['findmnt','-n','-o','SOURCE','/'],text=True).strip()
    serials=set(subprocess.check_output(['lsblk','-s','-n','-o','SERIAL',root],text=True).splitlines())
    serials={s.strip() for s in serials if s.strip()}
    if len(serials)!=1:
        raise SystemExit('Cannot bind the manually installed root to one physical disk serial')
    plan['host']['disk_serial']=serials.pop()
    state_path=target/'state.json';state=json.loads(state_path.read_text())
    state['plan_sha256']=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    pending.write_text(json.dumps({'plan':plan,'state':state})+'\n')
    for destination,value in [(plan_path,plan),(state_path,state)]:
        temporary=destination.with_name(destination.name+'.binding')
        temporary.write_text(json.dumps(value,indent=2)+'\n')
        os.replace(temporary,destination)
    pending.unlink()
PYBIND
python3 /opt/opendeploy/opendeploy.py register --job /opt/opendeploy
python3 /opt/opendeploy/host_health.py
