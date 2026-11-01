"""Freeze a public, credential-free release directory. Manifest hash is external."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    if str(path).lower().endswith(('.iso', '.iso.partial')):
        raise ValueError('ISO hashing is prohibited by user instruction')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def generate(root):
    files = []
    directories = []
    for path in sorted(root.rglob('*'), key=lambda p: p.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError(f'Symlink refused: {path}')
        if path.is_dir():
            directories.append(path.relative_to(root).as_posix())
        if path.is_file() and path != root / 'snapshot-manifest.json':
            entry = {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size}
            if not str(path).lower().endswith(('.iso', '.iso.partial')):
                entry['sha256'] = digest(path)
            files.append(entry)
    return {'schema': 1, 'directories': directories, 'files': files}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    manifest = root / 'snapshot-manifest.json'
    actual = generate(root)
    if args.verify:
        expected = json.loads(manifest.read_text(encoding='utf-8'))
        for entry in expected['files']:
            if entry['path'].lower().endswith(('.iso', '.iso.partial')):
                entry.pop('sha256', None)
        if expected != actual:
            raise SystemExit('FAIL: file inventory, size or SHA-256 differs')
    else:
        with manifest.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(actual, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    print(f"PASS: {len(actual['files'])} files; manifest SHA256={digest(manifest)}")
