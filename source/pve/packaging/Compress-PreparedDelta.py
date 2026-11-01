"""Reuse the already-published static relay data when compressing media changes."""
import json
import pathlib
import shutil
import subprocess
import tarfile
import zipfile

root=pathlib.Path(r'I:\xxm\PXVIRT-Trial-20261021\dev\Delivery-20261027')
scope={}
script=(root/'Extract-PreparedMediaDelta-Exact.py').read_text()
exec(script.split('\nprivate=root/',1)[0],scope)
private=root/'private-export'
reference=private/'public-relay-reference.bin'
source=private/'prepared-media-delta.zip'
changes=private/'iso-byte-changes.bin'
with scope['pathlib'].Path(r'I:\xxm\PXVIRT-Trial-20261021\dev\vm\PXVIRT-Repo-Debug-20261022\Initial-Windows-80G.vdi').open('rb') as raw:
    disk=scope['Disk'](scope['ExactVDIReader'](scope['VDI'](raw)))
    fs=scope['NTFS'](next(p for p in disk.partitions if p.offset==554696704).open())
    with zipfile.ZipFile(fs.mft.get('PXVIRT-OneFolder/original-runtime.zip').open()) as original:
        with original.open('assets/linux-x64.tar.gz') as stream,tarfile.open(fileobj=stream,mode='r|gz') as archive,reference.open('wb') as dest:
            for member in archive:
                if member.isfile():
                    with archive.extractfile(member) as data:shutil.copyfileobj(data,dest,1024*1024)
with zipfile.ZipFile(source) as archive,archive.open('iso.patch') as src,changes.open('wb') as dest:
    shutil.copyfileobj(src,dest,1024*1024)
compressed=private/'iso-byte-changes.zst'
zstd=pathlib.Path(r'I:\xxm\PXVIRT-Trial-20261021\release\OpenDeploy-Windows-Snapshot\runtime\usr\bin\zstd.exe')
subprocess.run([str(zstd),'-1','--single-thread','--long=28','--no-check','--patch-from='+reference.as_posix(),'-f',changes.as_posix(),'-o',compressed.as_posix()],check=True)
compact=private/'prepared-media-delta.compact.zip'
with zipfile.ZipFile(source) as old,zipfile.ZipFile(compact,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as new:
    for name in ['vdi.header','vdi.patch','media-layout.json']:new.writestr(name,old.read(name))
    new.write(compressed,'iso.patch.zst')
    new.writestr('reference.json',json.dumps({'method':'tar-regular-files-in-archive-order','asset':'assets/linux-x64.tar.gz','reference_bytes':reference.stat().st_size,'changes_bytes':changes.stat().st_size}))
compact.replace(source)
report={'reference_bytes':reference.stat().st_size,'raw_changes_bytes':changes.stat().st_size,'compact_delta_bytes':source.stat().st_size}
(root/'compact-delta-status.json').write_text(json.dumps(report))
print(json.dumps(report),flush=True)
