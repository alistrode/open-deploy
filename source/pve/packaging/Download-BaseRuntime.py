import pathlib,concurrent.futures,urllib.request,json,time
r=pathlib.Path(__file__).parent;m=json.loads((r/'base-snapshot-release.json').read_text());out=r/'base-parts';out.mkdir(exist_ok=True)
base='https://raw.githubusercontent.com/trlstdin/rororororo/dc41c5fe714cf61d60961d9070b67f3718a4a921/release/pve-windows-hostfix-20261021/'
def get(p):
 f=out/p['name']
 if f.exists() and f.stat().st_size==p['bytes']:return
 with urllib.request.urlopen(base+p['name'],timeout=120) as source,f.open('wb') as dest:
  while b:=source.read(1024*1024):dest.write(b)
 if f.stat().st_size!=p['bytes']:raise RuntimeError('Base part interrupted')
 print(p['name'],flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(get,m['parts']))
with (r/'base-runtime.zip').open('wb') as dest:
 for p in m['parts']:
  f=out/p['name']
  with f.open('rb') as source:
   while b:=source.read(8*1024*1024):dest.write(b)
  f.unlink()
print('Base runtime received', (r/'base-runtime.zip').stat().st_size,flush=True)
