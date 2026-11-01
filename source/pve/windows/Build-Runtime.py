"""Assemble the portable MSYS2 Windows build tools; never run an installer.

Build dependency: Python zstandard. Runtime dependencies are all bundled.
"""
import argparse
import concurrent.futures
import hashlib
import io
import json
import pathlib
import re
import shutil
import tarfile
import urllib.request
import zipfile
import zstandard


def sha(data):
    return hashlib.sha256(data).hexdigest()


def download(url, path, expected=None):
    if not path.exists():
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        if expected and sha(data) != expected:
            raise ValueError('Download hash mismatch: ' + url)
        path.write_bytes(data)
    data = path.read_bytes()
    if expected and sha(data) != expected:
        raise ValueError('Cached hash mismatch: ' + str(path))
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--destination', required=True, type=pathlib.Path)
    ap.add_argument('--cache', required=True, type=pathlib.Path)
    args = ap.parse_args()
    root, cache = args.destination, args.cache
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'windows-runtime.lock.json').exists():
        raise ValueError('Completed runtime already exists; use a new destination')
    cache.mkdir(parents=True, exist_ok=True)
    base = 'https://repo.msys2.org/msys/x86_64/'
    locked = json.loads(pathlib.Path(__file__).with_name('runtime.lock.json').read_text())
    data = download(base + 'msys.db', cache / 'msys.db', locked['repository_database_sha256'])
    db = {}
    with tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)), mode='r|') as archive:
        for member in archive:
            if member.name.endswith('/desc'):
                text = archive.extractfile(member).read().decode()
                fields = dict(re.findall(r'%([^%]+)%\n(.*?)(?:\n\n|\Z)', text, re.S))
                db[fields['NAME']] = fields
    providers = {}
    for name, fields in db.items():
        for provided in fields.get('PROVIDES', '').splitlines():
            providers[re.split(r'[<>=]', provided)[0]] = name
    chosen = set()
    todo = ['msys2-runtime', 'bash', 'coreutils', 'python', 'xorriso', 'openssh', 'openssl']
    while todo:
        name = re.split(r'[<>=]', todo.pop())[0]
        name = name if name in db else providers.get(name, name)
        if name in chosen:
            continue
        if name not in db:
            raise ValueError('Unresolved dependency: ' + name)
        chosen.add(name)
        todo.extend(db[name].get('DEPENDS', '').splitlines())
    def fetch(name):
        fields = db[name]
        filename = fields['FILENAME']
        data = download(base + filename, cache / filename, fields['SHA256SUM'])
        return name, data
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        packages = list(pool.map(fetch, sorted(chosen)))
    records = []
    runtime = root / 'runtime'
    runtime.mkdir()
    for name, data in packages:
        fields = db[name]
        with tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)), mode='r|') as archive:
            # Package metadata is retained separately; avoid overwriting it.
            for member in archive:
                if member.name.startswith('.'):
                    continue
                archive.extract(member, runtime, filter='data')
        records.append({'name': name, 'version': fields['VERSION'],
                        'url': base + fields['FILENAME'], 'sha256': fields['SHA256SUM'],
                        'license': fields.get('LICENSE', ''), 'upstream': fields.get('URL', '')})
    # ZIP extraction on Windows must not require symlink privileges.
    for path in sorted(runtime.rglob('*')):
        if path.is_symlink():
            target = path.readlink()
            actual = runtime / str(target).lstrip('/') if target.is_absolute() else path.parent / target
            actual = actual.resolve(strict=True)
            if not actual.is_relative_to(runtime.resolve()) or not actual.is_file():
                raise ValueError('Unsupported runtime link: ' + str(path))
            data = actual.read_bytes()
            path.unlink()
            path.write_bytes(data)
    for folder in ['tmp', 'etc', 'home', 'dev']:
        (runtime / folder).mkdir(exist_ok=True)
    (runtime / 'etc/fstab').write_text('none /tmp usertemp binary,posix=0 0 0\n', encoding='ascii')
    wim_url = 'https://wimlib.net/downloads/wimlib-1.14.5-windows-x86_64-bin.zip'
    wim_lock = next(p for p in locked['packages'] if p['name'] == 'wimlib')
    wim = download(wim_url, cache / 'wimlib-1.14.5-windows-x86_64-bin.zip', wim_lock['sha256'])
    with zipfile.ZipFile(io.BytesIO(wim)) as archive:
        archive.extractall(root / 'wimlib')
    records.append({'name': 'wimlib', 'version': '1.14.5', 'url': wim_url,
                    'sha256': sha(wim), 'hash_provenance': 'Measured HTTPS download'})
    native = next(p for p in locked['packages'] if p['name'] == 'python-windows-embedded')
    data = download(native['url'], cache / native['url'].rsplit('/', 1)[1], native['sha256'])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(root / 'python')
    records.append({key: value for key, value in native.items() if key != 'status'})
    (root / 'windows-runtime.lock.json').write_text(json.dumps({
        'repository_database_sha256': sha((cache / 'msys.db').read_bytes()),
        'packages': records}, indent=2) + '\n')
    print(f'Bundled {len(records)} packages at {root}')


if __name__ == '__main__':
    main()
