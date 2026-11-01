#!/usr/bin/env python3
"""Fetch pinned PXVIRT, relay 3.0 and VirtIO files. Never download the user's Windows ISO."""
import argparse,hashlib,json,pathlib,shutil,urllib.request

def sha(p):
    if str(p).lower().endswith(('.iso','.iso.partial')):raise ValueError('ISO hashing is prohibited by user instruction')
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--destination',type=pathlib.Path,required=True);a.add_argument('--verify-only',action='store_true');args=a.parse_args()
    lock=json.loads((pathlib.Path(__file__).parent/'dependencies.lock.json').read_text());root=args.destination.resolve()
    if not args.verify_only:root.mkdir(parents=True,exist_ok=True)
    results={}
    for name in ['pxvirt','relay','virtio']:
        item=lock[name];dest=root/pathlib.PurePosixPath(item['url']).name
        is_iso=dest.suffix.lower()=='.iso'
        valid=lambda:dest.is_file() and dest.stat().st_size==item['bytes'] and (is_iso or sha(dest)==item['sha256'])
        if not valid():
            if args.verify_only:raise SystemExit('Missing or corrupt file: '+name)
            tmp=dest.with_suffix(dest.suffix+'.partial')
            try:
                with urllib.request.urlopen(item['url'],timeout=180) as response,tmp.open('wb') as f:shutil.copyfileobj(response,f,1024*1024)
                if tmp.stat().st_size!=item['bytes'] or (not is_iso and sha(tmp)!=item['sha256']):raise ValueError('Download differs: '+name)
                tmp.replace(dest)
            finally:tmp.unlink(missing_ok=True)
        results[name]=str(dest)
    print(json.dumps(results))
if __name__=='__main__':main()
