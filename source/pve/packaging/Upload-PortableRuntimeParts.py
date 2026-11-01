"""Upload new binary part bodies; the GitHub connector publishes the tree/ref."""
import base64
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).parent
result = []
for item in json.loads((ROOT / 'runtime-upload-files.json').read_text()):
    payload = json.dumps({'encoding': 'base64', 'content': base64.b64encode(pathlib.Path(item['path']).read_bytes()).decode('ascii')})
    response = subprocess.run(['gh', 'api', 'repos/trlstdin/rororororo/git/blobs',
                               '--method', 'POST', '--input', '-'],
                              input=payload, text=True, capture_output=True, check=True)
    value = json.loads(response.stdout)
    result.append({'path': 'release/simulation-used-20261025/' + item['name'],
                   'mode': '100644', 'type': 'blob', 'sha': value['sha']})
    print('Uploaded binary part ' + item['name'], flush=True)
(ROOT / 'uploaded-tree-entries.json').write_text(json.dumps(result, indent=2) + '\n')
