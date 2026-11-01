set -e
python3 - <<'PY'
import sys,pathlib,json,socket,subprocess,shlex
j=pathlib.Path('/opt/opendeploy');sys.path.insert(0,str(j));import opendeploy as od
p=json.loads((j/'plan.json').read_text());od.Host(p).owned();marker='OpenDeploy-'+p['id']
s=socket.create_connection(('10.110.0.10',3389),timeout=4);s.close()
rules=[['-t','nat','PREROUTING','-i','vmbr0','-s','10.0.2.2/32','-d','10.0.2.15/32','-p','tcp','--dport','3389','-m','comment','--comment',marker,'-j','DNAT','--to-destination','10.110.0.10:3389'],['FORWARD','-i','vmbr0','-o','vmbr110','-s','10.0.2.2/32','-d','10.110.0.10/32','-p','tcp','--dport','3389','-m','comment','--comment',marker,'-j','ACCEPT']]
def cmd(r,op):
 i=2 if r[:1]==['-t'] else 0
 return ['iptables',*r[:i],op,*r[i:]]
f=pathlib.Path('/etc/network/interfaces.d/opendeploy-tiny10');text=f.read_text();assert text.startswith('# '+marker+' ')
for r in rules:
 if subprocess.run(cmd(r,'-C'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:subprocess.run(cmd(r,'-A'),check=True)
 line='    post-up '+shlex.join(cmd(r,'-C'))+' || '+shlex.join(cmd(r,'-A'))+'\n'
 if line not in text:text+=line+'    post-down '+shlex.join(cmd(r,'-D'))+' || true\n'
f.write_text(text)
print('Connected existing host RDP forward through guest-only scoped NAT')
PY
systemctl start --no-block opendeploy-guest.service
