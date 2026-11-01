"""Install a complete first-boot payload without mixing deployment identities."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

RELAY_SHA = '59c1716194a3e2bbaa2cdce9fa84ed3463b0ab1c77f7d1640874a4448a50deda'
IDENTITY = ('host_key', 'host_key.pub', 'client_key.pub', 'remote.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(source, target, live=pathlib.Path('/var/lib/opendeploy/relay3')):
    source, target = pathlib.Path(source), pathlib.Path(target)
    plan = json.loads((source/'plan.json').read_text())
    if target.exists():
        if json.loads((target/'plan.json').read_text())['id'] != plan['id']:
            raise ValueError('Another deployment occupies the installed directory')
        for name in IDENTITY:
            if digest(source/'relay-state'/name) != digest(target/'relay-state'/name):
                raise ValueError('Deployment identity differs; existing files retained')
        # The installed directory is an atomic snapshot. Do not replay old USB
        # state or overwrite keys on a retry after registration has progressed.
        if not (target/'relay/SSH-Remote-Linux/runtime/node').is_file():
            raise ValueError('Installed payload incomplete; retained for inspection')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = pathlib.Path(tempfile.mkdtemp(prefix='.opendeploy-', dir=target.parent))
        try:
            shutil.copytree(source, staging, dirs_exist_ok=True)
            os.chmod(staging, 0o700)
            archive = staging/'relay.tar.gz'
            if archive.exists():
                if digest(archive) != RELAY_SHA:
                    raise ValueError('Pinned relay archive differs')
                (staging/'relay').mkdir(exist_ok=True)
                subprocess.run(['tar', '-xzf', str(archive), '-C', str(staging/'relay')], check=True)
            node = staging/'relay/SSH-Remote-Linux/runtime/node'
            os.chmod(node, 0o755)
            for name in IDENTITY:
                if not (staging/'relay-state'/name).is_file():
                    raise ValueError('Deployment identity is incomplete')
            state = json.loads((staging/'state.json').read_text())
            expected = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if state['plan_sha256'] != expected:
                raise ValueError('Payload plan and state differ')
            # Check live identity before publishing a new application directory.
            _check_live(staging, live)
            os.rename(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    _check_live(target, live)


def _check_live(target, live):
    if live.exists():
        for name in IDENTITY:
            if digest(target/'relay-state'/name) != digest(live/name):
                raise ValueError('Running relay identity differs; retained')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=pathlib.Path)
    parser.add_argument('target', type=pathlib.Path)
    args = parser.parse_args()
    install(args.source, args.target)
