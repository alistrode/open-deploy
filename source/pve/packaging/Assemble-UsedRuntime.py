"""Assemble the original used folder from its original base and actual source overlay.

No installer changes, no image hashes, no new installation. The Windows folder
used junctions to these base dependencies; the delivered folder contains them.
"""
import json
import pathlib
import shutil
import urllib.request
import zipfile

root = pathlib.Path(__file__).parent
headers = {'Cookie': 'verified=2024-05-24'}
url = 'https://filebin.net/opendeploy-direct-20261027-fast/used-runtime-files.json'
with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
    raw = response.read()
(root/'used-runtime-files.json').write_bytes(raw)
inventory = json.loads(raw)['files']
output = root/'OpenDeploy-Used-PXVIRTOnly-Windows-20261025.zip'
with zipfile.ZipFile(root/'base-runtime.zip') as base, zipfile.ZipFile(root/'used-source-overlay.zip') as overlay, zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as target:
    owned = set(overlay.namelist())
    for index, entry in enumerate(inventory):
        name = 'OpenDeploy/' + entry['path']
        archive = overlay if name in owned else base
        source_name = name if archive is overlay else entry['path']
        info = archive.getinfo(source_name)
        if info.file_size != entry['bytes']:
            raise RuntimeError('Dependency source length differs: '+entry['path'])
        with archive.open(source_name) as source, target.open(name,'w',force_zip64=True) as dest:
            shutil.copyfileobj(source,dest,1024*1024)
        if index%500==0:print(json.dumps({'files':index+1,'total':len(inventory)}),flush=True)
print(json.dumps({'files':len(inventory),'bytes':output.stat().st_size,'archive':str(output)}),flush=True)
