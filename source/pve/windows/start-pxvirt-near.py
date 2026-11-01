#!/usr/bin/env python3
"""Start the original PXVIRT Relay 3.0 near end; never reboot the target."""
import argparse,json,os,shutil,socket,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--runtime-root',type=Path,required=True);p.add_argument('--identity-dir',type=Path,required=True);p.add_argument('--state-dir',type=Path,required=True);a=p.parse_args()
os.umask(0o077);state=a.state_dir.resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700)
pidfile=state/'near.pid'
if pidfile.exists():
 pid=int(pidfile.read_text()); cmdline=Path(f'/proc/{pid}/cmdline')
 if cmdline.exists() and str(state/'near.json').encode() in cmdline.read_bytes():
  print('Existing original near-end process retained:',pid);raise SystemExit(0)
for n in ['client_key','known_hosts','connection-private.json']:
 shutil.copyfile(a.identity_dir/n,state/n);(state/n).chmod(0o600)
cfg=json.loads((a.identity_dir/'near.json').read_text(encoding='utf-8-sig'))
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
cfg.update(localPort=port,statusPath=str(state/'peer.json'))
(state/'near.json').write_text(json.dumps(cfg));(state/'near.json').chmod(0o600)
(state/'peer.json').unlink(missing_ok=True)
root=a.runtime_root.resolve()
with (state/'near.log').open('ab') as log:
 child=subprocess.Popen([str(root/'runtime/node'),str(root/'src/near.cjs'),str(state/'near.json')],stdout=log,stderr=log,start_new_session=True,cwd=root)
pidfile.write_text(str(child.pid))
for _ in range(100):
 if child.poll() is not None:raise SystemExit('Near end exited; inspect private near.log without publishing credentials')
 log=(state/'near.log').read_text(errors='replace')
 if 'Near-end public relay subscribed.' in log:
  print(json.dumps({'pid':child.pid,'local_port':port,'broker_subscribed':True,'peer_status_present':(state/'peer.json').exists(),'state_dir':str(state)}));break
 time.sleep(.3)
else:raise SystemExit('Near end running; broker subscription not yet confirmed; inspect private log')
