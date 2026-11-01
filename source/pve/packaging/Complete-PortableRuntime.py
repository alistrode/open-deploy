"""Complete the portable ZIP by adding current application code, without extraction.

This edits an archive only. It does not restore, launch, test, or verify the app.
Existing compressed dependency bytes are retained verbatim. The central directory
names each replaced application file once; superseded local records are ignored
by ZIP readers. Publication can reuse complete untouched prefix-part Git blobs.
"""
import copy
import json
import pathlib
import shutil
import zipfile

ROOT = pathlib.Path(__file__).parent
REPO = ROOT / 'repo'
STAGING = ROOT / 'staging' / 'OpenDeploy'
PART_SIZE = 16 * 1024 * 1024
NAME = 'OpenDeploy-Windows-Full-20261027.zip'

STAGING.mkdir(parents=True, exist_ok=True)
shutil.copytree(REPO / 'source/pve', STAGING / 'source/pve', dirs_exist_ok=True)
for source in (REPO / 'source/pve/windows').iterdir():
    if source.suffix.lower() in ('.ps1', '.cmd'):
        shutil.copyfile(source, STAGING / source.name)
shutil.copyfile(REPO / 'source/pve/Verify-Snapshot.ps1', STAGING / 'Verify-Snapshot.ps1')
shutil.copytree(REPO / '.agents', STAGING / '.agents', dirs_exist_ok=True)
shutil.copytree(REPO / 'docs', STAGING / 'docs', dirs_exist_ok=True)
(STAGING / 'PACKAGE-NOTES.txt').write_text(
    'OpenDeploy Windows full package, supplemented 2026-10-27.\n'
    'Start: Start-Windows.cmd. Application code is under source/pve.\n'
    'Original runtime/dependencies/resources are retained. Current application\n'
    'code and complete existing recovery scripts/configuration are included.\n'
    'Read .agents/skills/opendeploy-recovery/SKILL.md for recovery scope.\n'
    'Recovery files are not automatic installation hooks. Do not replay recovery\n'
    'on the already completed installation or copy simulation addresses to hardware.\n'
    'Tiny10 ISO is excluded at user request. Chinese offline input is a separate\n'
    'artifact in delivery-parts.json. Original sealed ISO/VDI remain original media.\n'
    'No new whole-package extraction, execution, comparison or acceptance was\n'
    'performed. Ask the user before any later verification.\n', encoding='utf-8')

archive = ROOT / NAME
shutil.copyfile(ROOT / 'runtime-original.zip', archive)
new_files = {p.relative_to(STAGING.parent).as_posix(): p
             for p in STAGING.rglob('*') if p.is_file()}
with zipfile.ZipFile(archive, 'a', compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                     allowZip64=True) as output:
    preserved_prefix = output.start_dir
    # Replace central-directory entries while preserving original compressed data.
    output.filelist = [entry for entry in output.filelist if entry.filename not in new_files]
    output.NameToInfo = {entry.filename: entry for entry in output.filelist}
    for name, source in sorted(new_files.items()):
        output.write(source, name)

original = json.loads((ROOT / 'delivery-parts.json').read_text())
old = next(a for a in original['artifacts'] if a['kind'] == 'Runtime')
tree = {x['path']: x for x in json.loads((ROOT / 'tree.json').read_text())['tree']}
manifest = copy.deepcopy(original)
runtime = next(a for a in manifest['artifacts'] if a['kind'] == 'Runtime')
runtime.update(name=NAME, bytes=archive.stat().st_size, parts=[])
prefix_parts = preserved_prefix // PART_SIZE
entries = []
upload = []
published = ROOT / 'publish'
published.mkdir(exist_ok=True)
with archive.open('rb') as source:
    index = 0
    while data := source.read(PART_SIZE):
        name = NAME + '.part' + str(index).zfill(3)
        runtime['parts'].append({'name': name, 'bytes': len(data)})
        if index < prefix_parts:
            original_path = 'release/simulation-used-20261025/' + old['parts'][index]['name']
            entries.append({'path': 'release/simulation-used-20261025/' + name,
                            'mode': '100644', 'type': 'blob', 'sha': tree[original_path]['sha']})
        else:
            path = published / name
            path.write_bytes(data)
            upload.append({'path': str(path), 'name': name})
        index += 1
for part in old['parts']:
    entries.append({'path': 'release/simulation-used-20261025/' + part['name'],
                    'mode': '100644', 'type': 'blob', 'sha': None})
(ROOT / 'new-delivery-parts.json').write_text(json.dumps(manifest, indent=2) + '\n')
(ROOT / 'runtime-tree-entries.json').write_text(json.dumps(entries, indent=2) + '\n')
(ROOT / 'runtime-upload-files.json').write_text(json.dumps(upload, indent=2) + '\n')
(ROOT / 'package-result.json').write_text(json.dumps({
    'name': NAME, 'bytes': runtime['bytes'], 'parts': len(runtime['parts']),
    'files_added_or_replaced': len(new_files), 'reused_prefix_parts': prefix_parts,
    'new_part_bodies': len(upload), 'extracted': False, 'executed': False,
    'verified': False}, indent=2) + '\n')
print((ROOT / 'package-result.json').read_text(), flush=True)
