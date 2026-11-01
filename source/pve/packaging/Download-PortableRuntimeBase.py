import concurrent.futures
import base64
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).parent
REPO = 'trlstdin/rororororo'
REF = '65f0afc5b5754e2cdfc6adc528a754718963374c'
PREFIX = 'release/simulation-used-20261025/'
TREE = {x['path']: x for x in json.loads((ROOT / 'tree.json').read_text())['tree']}

def download(name):
    target = ROOT / 'original-parts' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target
    temporary = target.with_suffix(target.suffix + '.downloading')
    endpoint = 'repos/' + REPO + '/git/blobs/' + TREE[PREFIX + name]['sha']
    response = subprocess.run(['gh', 'api', endpoint], capture_output=True, check=True)
    temporary.write_bytes(base64.b64decode(json.loads(response.stdout)['content']))
    temporary.replace(target)
    print('Downloaded ' + name, flush=True)
    return target

manifest = json.loads((ROOT / 'delivery-parts.json').read_text())
artifact = next(a for a in manifest['artifacts'] if a['kind'] == 'Runtime')
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(download, [p['name'] for p in artifact['parts']]))
output = ROOT / 'runtime-original.zip'
with output.open('wb') as destination:
    for part in artifact['parts']:
        with (ROOT / 'original-parts' / part['name']).open('rb') as source:
            while data := source.read(8 * 1024 * 1024):
                destination.write(data)
print('Original ZIP assembled for archive editing; not extracted or run.', flush=True)
