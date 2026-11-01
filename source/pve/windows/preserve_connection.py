"""Keep the AI connection identity on the installation USB before OS replacement."""
import hashlib
import json
import os
import pathlib
import shutil
import tempfile

FILES = ('client_key', 'client_key.pub', 'connection-private.json', 'near.json', 'known_hosts')


def preserve(job, usb):
    job, usb = pathlib.Path(job), pathlib.Path(usb)
    plan = json.loads((job/'plan.json').read_text())
    source = job/'ai-private'
    hashes = {name: hashlib.sha256((source/name).read_bytes()).hexdigest() for name in FILES}
    identity = json.loads((source/'connection-private.json').read_text())
    if identity.get('clientPrivateKey', '').strip() != (source/'client_key').read_text().strip():
        raise ValueError('AI private key and saved connection identity differ')
    remote = json.loads((job/'media/payload/relay-state/remote.json').read_text())
    for key in ('broker', 'session', 'secret', 'user', 'fingerprint'):
        if identity[key] != remote[key]:
            raise ValueError('AI and deployed connection identity differ')
    private = usb/'OpenDeploy-private'
    private.mkdir(exist_ok=True)
    target = private/'ai-private'
    manifest = {'schema': 1, 'plan_id': plan['id'], 'files': hashes}
    if target.exists():
        if json.loads((target/'backup.json').read_text()) != manifest:
            raise ValueError('Existing USB identity backup differs; retained')
    else:
        staging = pathlib.Path(tempfile.mkdtemp(prefix='.identity-', dir=private))
        try:
            for name in FILES:
                shutil.copyfile(source/name, staging/name)
            (staging/'backup.json').write_text(json.dumps(manifest, indent=2)+'\n')
            os.rename(staging, target)
        finally:
            if staging.exists(): shutil.rmtree(staging)
    for name, expected in hashes.items():
        if hashlib.sha256((target/name).read_bytes()).hexdigest() != expected:
            raise ValueError('USB identity backup verification failed')
    return target


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=pathlib.Path, required=True)
    parser.add_argument('--usb', type=pathlib.Path, required=True)
    args = parser.parse_args()
    preserve(args.job, args.usb)
    print('Connection identity backup verified on USB; no credentials printed.')
