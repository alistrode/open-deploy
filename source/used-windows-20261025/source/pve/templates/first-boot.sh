#!/bin/bash
set -euo pipefail
umask 077
expected='__PLAN_ID__'
mountpoint=$(mktemp -d /run/opendeploy-media.XXXXXX)
cleanup() { mountpoint -q "$mountpoint" && umount "$mountpoint" || true; rmdir "$mountpoint" || true; }
trap cleanup EXIT
found=0
while IFS= read -r device; do
    if mount -t iso9660 -o ro "$device" "$mountpoint" 2>/dev/null; then
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
python3 - "$mountpoint/opendeploy" <<'PY'
import json,pathlib,shutil,sys,os
source=pathlib.Path(sys.argv[1]);target=pathlib.Path('/opt/opendeploy')
if (target/'plan.json').exists():
    if json.loads((target/'plan.json').read_text())['id']!=json.loads((source/'plan.json').read_text())['id']:
        raise SystemExit('Another deployment already occupies /opt/opendeploy')
target.mkdir(mode=0o700,parents=True,exist_ok=True)
for path in source.rglob('*'):
    if not path.is_file():continue
    dest=target/path.relative_to(source)
    if path.name=='state.json' and dest.exists():continue
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_name(dest.name+'.copying')
    shutil.copy2(path,tmp)
    os.replace(tmp,dest)
os.chmod(target,0o700)
os.chmod(target/'relay/SSH-Remote-Linux/runtime/node',0o755)
PY
python3 /opt/opendeploy/host_health.py
python3 /opt/opendeploy/opendeploy.py register --job /opt/opendeploy
