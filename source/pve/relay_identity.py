"""Create one job-owned connection identity, then export both peers from it."""
import base64
import hashlib
import json
import os
import pathlib
import secrets
import shutil
import subprocess
import tempfile


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def initialize(job, payload):
    job, payload = pathlib.Path(job), pathlib.Path(payload)
    identity = job/'connection-identity'
    near, far = job/'ai-private', payload/'relay-state'
    if not identity.exists():
        staging = pathlib.Path(tempfile.mkdtemp(prefix='.connection-identity-', dir=job))
        try:
            legacy_info = far/'connection-private.json'
            # Import an existing job as a whole, without generating replacement
            # keys or sessions in either peer's output directory.
            if legacy_info.exists():
                for source, name in [(far/'host_key', 'host_key'),
                                     (far/'host_key.pub', 'host_key.pub'),
                                     (near/'client_key', 'client_key'),
                                     (near/'client_key.pub', 'client_key.pub'),
                                     (legacy_info, 'connection-private.json')]:
                    shutil.copyfile(source, staging/name)
            else:
                # Partial legacy output must never silently become a new identity.
                if any((folder/name).exists() for folder, name in
                       [(far, 'host_key'), (near, 'client_key'), (near, 'connection-private.json')]):
                    raise ValueError('Existing connection identity is incomplete; retained without replacement')
                for name in ('host_key', 'client_key'):
                    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(staging/name)], check=True)
                public = (staging/'host_key.pub').read_text().split()
                fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(public[1])).digest()).decode().rstrip('=')
                write_json(staging/'connection-private.json', {
                    'version': 1, 'target': 'linux', 'broker': 'wss://broker.emqx.io:8084/mqtt',
                    'session': secrets.token_hex(16), 'secret': secrets.token_hex(32),
                    'user': 'relay', 'fingerprint': fingerprint,
                    'hostPublicKey': ' '.join(public[:2]),
                    'clientPrivateKey': (staging/'client_key').read_text()})
            for path in staging.iterdir():
                path.chmod(0o600)
            # Only a complete identity becomes the permanent source.
            os.rename(staging, identity)
        finally:
            if staging.exists(): shutil.rmtree(staging)
    info = json.loads((identity/'connection-private.json').read_text())
    far.mkdir(mode=0o700, parents=True, exist_ok=True)
    near.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Everything below is derived output. No randomness or key creation here.
    for name in ('host_key', 'host_key.pub', 'client_key.pub', 'connection-private.json'):
        shutil.copyfile(identity/name, far/name)
    for name in ('client_key', 'client_key.pub', 'connection-private.json'):
        shutil.copyfile(identity/name, near/name)
    config = {k: v for k, v in info.items() if k not in ('clientPrivateKey', 'hostPublicKey')}
    write_json(far/'remote.json', config | {'sshPort': 0})
    write_json(near/'near.json', {k: info[k] for k in ('broker', 'session', 'secret', 'user', 'fingerprint')} |
               {'localPort': 0, 'statusPath': str(near/'peer.json')})
    (near/'known_hosts').write_text('opendeploy-pve '+info['hostPublicKey']+'\n', encoding='utf-8')
    for folder in (far, near):
        for path in folder.iterdir():
            if path.is_file(): path.chmod(0o600)
