"""Upload received binary parts via GitHub CLI without printing their contents.

The connector remains responsible for final tree/commit/ref publication. CLI is
used for large local file bodies that exceed orchestration text output limits.
"""
import base64
import concurrent.futures
import json
import pathlib
import subprocess
import time

root = pathlib.Path(__file__).parent
received = root / 'received'
cache = root / 'github-artifact-blobs.json'
known = json.loads(cache.read_text()) if cache.exists() else {}
first = root / 'first-artifact-blob.json'
if first.exists():
    value = json.loads(first.read_text())
    known[value['file'] + '.seg000'] = {'sha': value['sha'], 'bytes': value['bytes']}

SEGMENT = 16 * 1024 * 1024

def upload(item):
    path, name, offset, size = item
    with path.open('rb') as handle:
        handle.seek(offset)
        data = handle.read(size)
    request = {'content': base64.b64encode(data).decode(), 'encoding': 'base64'}
    body=json.dumps(request)
    for attempt in range(4):
        proc = subprocess.run(['gh','api','repos/trlstdin/rororororo/git/blobs','--method','POST','--input','-'],input=body,text=True,capture_output=True,timeout=90)
        if proc.returncode==0:break
        print(json.dumps({'retry':attempt+1,'file':name,'reason':proc.stderr[-150:]}),flush=True)
        time.sleep(2*(attempt+1))
    if proc.returncode:raise RuntimeError(name + ': ' + proc.stderr[-800:])
    value = json.loads(proc.stdout)
    return name, {'sha': value['sha'], 'bytes': size}

started = time.monotonic()
while time.monotonic() - started < 10800:
    files = []
    for path in list(received.iterdir()) + list((root/'runtime-parts').glob('*')) + list((root/'media-parts').glob('*')) + list((root/'input-parts').glob('*')):
        if not path.is_file() or path.name.endswith(('.downloading', '.sftp')):
            continue
        if path.name.startswith('tiny10-x64-23h2.iso.part'):
            continue
        size = path.stat().st_size
        if '.part' in path.name and size > SEGMENT:
            for index, offset in enumerate(range(0, size, SEGMENT)):
                name = path.name + '.seg' + str(index).zfill(3)
                if name not in known:
                    files.append((path, name, offset, min(SEGMENT, size-offset)))
        elif path.name not in known:
            files.append((path, path.name, 0, size))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pending=[pool.submit(upload,item) for item in files]
        failures=[]
        for task in concurrent.futures.as_completed(pending):
            try:name,value=task.result()
            except Exception as error:
                failures.append(str(error));print(str(error),flush=True);continue
            known[name] = value
            temporary=cache.with_suffix('.new')
            temporary.write_text(json.dumps(known, indent=2));temporary.replace(cache)
            print(json.dumps({'uploaded_files': len(known), 'uploaded_bytes': sum(v['bytes'] for v in known.values()), 'latest': name}), flush=True)
    marker = root / 'all-artifacts-received.json'
    if marker.exists():
        required = json.loads(marker.read_text())['files']
        if all(name in known for name in required):
            print('All artifact blobs uploaded', flush=True)
            break
    time.sleep(5)
else:
    raise RuntimeError('Artifact upload deadline exceeded')
