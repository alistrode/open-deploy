set -e
systemctl stop opendeploy-guest.service
python3 - <<'PY'
import sys,pathlib,json,socket,time,select,datetime
j=pathlib.Path('/opt/opendeploy');sys.path.insert(0,str(j));import opendeploy as od
p=json.loads((j/'plan.json').read_text());od.Host(p).owned();intent=j/'controlled-guest-reboot-after-firewall.json'
if intent.exists():raise RuntimeError('Reboot request already recorded; inspect its result instead of replaying')
q=socket.socket(socket.AF_UNIX);q.settimeout(10);q.connect('/var/run/qemu-server/110.qmp');f=q.makefile('rwb',buffering=0);f.readline();f.write(b'{"execute":"qmp_capabilities"}\n')
while 'return' not in json.loads(f.readline()):pass
s=socket.socket(socket.AF_UNIX);s.settimeout(20);s.connect('/var/run/qemu-server/110.qga');g=s.makefile('rwb',buffering=0);token=int(time.time());g.write((json.dumps({'execute':'guest-sync','arguments':{'id':token}})+'\n').encode())
while json.loads(g.readline().lstrip(b'\xff')).get('return')!=token:pass
record={'id':p['id'],'uuid':p['vm']['uuid'],'state':'requested','requestedAt':datetime.datetime.now(datetime.timezone.utc).isoformat()};od.atomic(intent,record)
g.write(b'{"execute":"guest-shutdown","arguments":{"mode":"reboot"}}\n');time.sleep(.2);s.close()
end=time.monotonic()+110;buf=b''
while time.monotonic()<end:
 if not select.select([q],[],[],min(5,end-time.monotonic()))[0]:continue
 data=q.recv(65536)
 if not data:break
 buf+=data
 while b'\n' in buf:
  line,buf=buf.split(b'\n',1)
  if not line:continue
  event=json.loads(line)
  if event.get('event')=='RESET':
   record.update({'state':'reset_observed','event':event});od.atomic(intent,record)
   pending=j/'guest-readiness-process.json'
   if pending.exists():
    old=json.loads(pending.read_text());assert old['id']==p['id'] and old['uuid']==p['vm']['uuid'];pending.unlink()
   for path in (j/'guest-console-operations').glob('*.json'):
    op=json.loads(path.read_text())
    if op.get('state')=='running':op['state']='interrupted_by_controlled_guest_reboot';od.atomic(path,op)
   print('Controlled guest reboot confirmed by QMP RESET; stale read queries retired')
   raise SystemExit(0)
print('Reboot request preserved; RESET has not yet been observed')
PY
