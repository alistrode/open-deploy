#!/usr/bin/env python3
"""Package a prepared Windows runtime; never fetch unpinned dependencies implicitly."""
import argparse, hashlib, io, json, pathlib, tarfile

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);args=p.parse_args()
    root=args.runtime.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    required=['OpenDeploy.exe','Start.cmd','1-Prepare.cmd','2-Install.cmd','3-Drivers.cmd','bootstrap-drivers','drivers-manifest.json','scripts/Build-WinPE.ps1','scripts/Install-Drivers.ps1','osd/OpenDeploy-OSD.ps1','upstream/OSD/OSD.psd1','vendor/sdio/SDIO_x64_R887.exe','dependencies.lock.json']
    for name in required:
        if not (root/name).exists():raise SystemExit('Missing runtime component: '+name)
    for f in json.loads((root/'drivers-manifest.json').read_text())['Files']:
        path=root/f['Path']
        if path.stat().st_size!=f['Size'] or sha(path)!=f['SHA256']:raise SystemExit('Driver integrity failure: '+f['Path'])
    archive=out/'OpenDeploy-runtime-components.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for f in sorted(root.rglob('*')):
            if f.is_file():tar.add(f,arcname=f.relative_to(root).as_posix(),recursive=False)
    # Remove only previous generated chunks, after the new archive was produced.
    for f in out.glob('OpenDeploy-runtime-components.tar.gz.part*'):f.unlink()
    parts=[]
    with archive.open('rb') as stream:
        n=0
        while block:=stream.read(40*1024*1024):
            name=archive.name+f'.part{n:03d}';path=out/name;path.write_bytes(block)
            parts.append({'name':name,'bytes':len(block),'sha256':sha(path)});n+=1
    files=[{'path':f.relative_to(root).as_posix(),'bytes':f.stat().st_size,'sha256':sha(f)} for f in sorted(root.rglob('*')) if f.is_file()]
    manifest={'name':archive.name,'bytes':archive.stat().st_size,'sha256':sha(archive),'parts':parts,'files':files,'driver_binaries_included':True,'current_executable_sha256':sha(root/'OpenDeploy.exe'),'validation_status':'Windows native installation not yet verified'}
    (out/'runtime-components-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive.unlink()
    print(json.dumps({'archive_bytes':manifest['bytes'],'parts':len(parts),'files':len(files),'sha256':manifest['sha256']}))
if __name__=='__main__':main()
