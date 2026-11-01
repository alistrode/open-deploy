#!/usr/bin/env python3
"""Restore the pinned Microsoft build layout; this does not build or validate PE."""
import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import shutil
import urllib.request


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def checked_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Invalid layout path: ' + relative)
    return path


def restore(root, entry, verify_only):
    path = checked_path(root, entry['path'])
    def valid():
        return path.is_file() and path.stat().st_size == entry['bytes'] and digest(path) == entry['sha256']
    if valid():
        return
    if verify_only:
        raise ValueError('Missing or corrupt layout file: ' + entry['path'])
    url = entry['url']
    if not url.startswith('https://download.microsoft.com/'):
        raise ValueError('Unexpected layout origin: ' + url)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.partial')
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as target:
            shutil.copyfileobj(response, target, 1024 * 1024)
        if temporary.stat().st_size != entry['bytes'] or digest(temporary) != entry['sha256']:
            raise ValueError('Downloaded layout integrity failure: ' + entry['path'])
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=pathlib.Path, required=True)
    parser.add_argument('--manifest', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1] / 'adk-layout.lock.json')
    parser.add_argument('--verify-only', action='store_true', help='Check every file without network access or writes')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    entries = manifest['files']
    root = args.destination.resolve()
    paths = [checked_path(root, entry['path']) for entry in entries]
    if len(set(paths)) != len(paths):
        raise ValueError('Duplicate paths in layout manifest')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(lambda entry: restore(root, entry, args.verify_only), entries):
            pass
    print(json.dumps({'verified_files': len(entries), 'bytes': sum(entry['bytes'] for entry in entries), 'pe_built': False}))


if __name__ == '__main__':
    main()
