"""Build a new candidate from a verified snapshot and committed source files.

The original frozen snapshot is never modified. A fresh manifest describes the
candidate; this does not assert that disk writing or installation has passed.
"""
import argparse
import json
import pathlib
import re
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from snapshot_manifest import generate, digest

ENTRIES = ('Start-Windows.ps1', 'Configure-Windows.ps1', 'Write-Usb.ps1', 'RawDisk.ps1', 'Continue-PXVIRT.cmd', 'Continue-PXVIRT.ps1')
CONTROLLER_FILES = ('snapshot_manifest.py', 'opendeploy.py', 'usb.py',
                    'Fetch-Dependencies.py', 'dependencies.lock.json', 'portal.py',
                    'workflow.json', 'host_health.py', 'first_boot_package.py')


def canonical_inventory(inventory):
    # Frozen snapshots can order paths by path components instead of the full
    # path string. Ordering does not alter inventory membership or file hashes.
    supported = {'schema', 'files', 'directories', 'source_commit', 'only_excluded_install_iso'}
    if set(inventory) - supported:
        raise ValueError('Unsupported manifest metadata')
    # Release provenance is checked separately; it is not a filesystem entry.
    result = {'schema': inventory['schema']}
    for field in ('files', 'directories'):
        entries = inventory[field]
        if field == 'files':
            entries = [({k: v for k, v in item.items() if k != 'sha256'}
                        if item['path'].lower().endswith(('.iso', '.iso.partial')) else item)
                       for item in entries]
        names = [item['path'] if field == 'files' else item for item in entries]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate inventory path: ' + field)
        result[field] = sorted(entries, key=lambda item: item['path'] if field == 'files' else item)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', type=pathlib.Path, required=True)
    ap.add_argument('--base-manifest-sha256', required=True)
    ap.add_argument('--source', type=pathlib.Path, required=True)
    ap.add_argument('--destination', type=pathlib.Path, required=True)
    args = ap.parse_args()
    base, source, out = args.base.resolve(), args.source.resolve(), args.destination.resolve()
    if out.exists() or out.is_relative_to(base) or base.is_relative_to(out) or out.is_relative_to(source):
        raise ValueError('Use a new destination outside the frozen base')
    manifest = base / 'snapshot-manifest.json'
    if digest(manifest) != args.base_manifest_sha256.lower():
        raise ValueError('Base manifest identity differs')
    expected = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if 'source_commit' in expected and expected['source_commit'] != (base / 'SOURCE-COMMIT.txt').read_text(encoding='utf-8-sig').strip():
        raise ValueError('Base source provenance differs')
    if canonical_inventory(generate(base)) != canonical_inventory(expected):
        raise ValueError('Base file inventory differs')
    identity = json.loads((source / 'source-identity.json').read_text(encoding='utf-8'))
    commit = identity['source_commit']
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('A real source commit is required')
    for entry in identity['files']:
        name = pathlib.PurePosixPath(entry['path'])
        if name.is_absolute() or '..' in name.parts or '\\' in str(name) or ':' in str(name):
            raise ValueError('Invalid source path')
        path = source / name
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError('Source link refused')
        if digest(path) != entry['sha256']:
            raise ValueError('Source payload hash differs: ' + str(name))
    bound = {entry['path'] for entry in identity['files']}
    if len(bound) != len(identity['files']):
        raise ValueError('Duplicate source path')
    required = {'source/pve/windows/' + name for name in ENTRIES} | {
        'source/pve/' + name for name in CONTROLLER_FILES
    } | {'source/pve/Verify-Snapshot.ps1', 'source/pve/templates/first-boot.sh'}
    if not required.issubset(bound):
        raise ValueError('Required source files are not bound by the source inventory')
    shutil.copytree(base, out)
    for name in ENTRIES:
        original = source / 'source/pve/windows' / name
        for relative in (name, 'source/pve/windows/' + name, 'project/source/pve/windows/' + name):
            destination = out / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
    for name in CONTROLLER_FILES:
        for prefix in ('source/pve/', 'project/source/pve/'):
            shutil.copyfile(source / 'source/pve' / name, out / prefix / name)
    verifier = 'source/pve/Verify-Snapshot.ps1'
    for relative in ('Verify-Snapshot.ps1', verifier, 'project/' + verifier):
        destination = out / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / verifier, destination)
    for prefix in ('source/pve/', 'project/source/pve/'):
        shutil.copytree(source/'source/pve/templates', out/prefix/'templates', dirs_exist_ok=True)
        shutil.copyfile(source/'source/pve/windows/build_windows.py', out/prefix/'windows/build_windows.py')
    # Do not introduce extra documentation into the application snapshot.
    (out / 'SOURCE-COMMIT.txt').write_text(commit + '\n', encoding='ascii')
    (out / 'FROZEN-AT.txt').write_text(datetime.now(timezone.utc).isoformat() + '\n', encoding='ascii')
    current = generate(out)
    (out / 'snapshot-manifest.json').write_text(json.dumps(current, indent=2) + '\n', encoding='utf-8')
    if generate(out) != current:
        raise ValueError('Candidate changed during freezing')
    print('Candidate file inventory verified; no disk or installation acceptance implied.')
    print(json.dumps({'source_commit': commit, 'files': len(current['files']),
                      'manifest_sha256': digest(out / 'snapshot-manifest.json')}))


if __name__ == '__main__':
    main()
