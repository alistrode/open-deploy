"""Native Windows builder bridge: direct CreateProcess, no Bash/WSL/Docker."""
import argparse
import importlib.util
import pathlib
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', type=pathlib.Path, required=True)
    ap.add_argument('--job', type=pathlib.Path)
    ap.add_argument('--disk-serial')
    ap.add_argument('--image-index', type=int, default=1)
    args = ap.parse_args()
    root = args.bundle.resolve()
    # The embedded Python is isolated by python312._pth. Include sibling
    # controller modules explicitly when loading opendeploy via importlib.
    sys.path.insert(0, str(root / 'source/pve'))
    spec = importlib.util.spec_from_file_location('opendeploy_windows', root / 'source/pve/opendeploy.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not args.job or not args.disk_serial:
        raise ValueError('Job directory and target disk serial required')
    args.job.mkdir(parents=True, exist_ok=True)
    plan_path = args.job / 'plan.json'
    if not plan_path.exists():
        mod.configure(argparse.Namespace(job=str(args.job),
            pxvirt=str(root / 'assets/pxvirt-8.4-2-amd64.iso'), relay=str(root / 'assets/linux-x64.tar.gz'),
            image_index=args.image_index,
            disk_serial=args.disk_serial, usb_device=None))
    plan = mod.load(plan_path)
    if plan['host']['disk_serial'] != args.disk_serial.strip():
        raise ValueError('Existing job belongs to different inputs; use a new job directory')
    with mod.locked(args.job / 'state.json'):
        mod.prepare(args.job, plan, mod.Journal(args.job / 'state.json', plan))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
