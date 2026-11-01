set -e
python3 - <<'PY'
import pathlib,json,subprocess,ipaddress,os
job=pathlib.Path('/opt/opendeploy');plan=json.loads((job/'plan.json').read_text());marker='OpenDeploy-'+plan['id']
c=dict(l.split(': ',1) for l in subprocess.check_output(['qm','config','110'],text=True).splitlines() if ': ' in l)
assert c['description']==marker and 'uuid='+plan['vm']['uuid'] in c['smbios1']
assert c['net0']=='e1000=BC:24:11:D5:1C:15,bridge=vmbr110'
assert 'source /etc/network/interfaces.d/*' in pathlib.Path('/etc/network/interfaces').read_text()
addr=json.loads(subprocess.check_output(['ip','-j','address','show','dev','vmbr110'],text=True))
assert any(a.get('local')=='10.110.0.1' and a.get('prefixlen')==24 for i in addr for a in i['addr_info'])
rules=[['-t','nat','POSTROUTING','-s','10.110.0.0/24','-o','vmbr0','-m','comment','--comment',marker,'-j','MASQUERADE'],['FORWARD','-i','vmbr110','-o','vmbr0','-s','10.110.0.0/24','-m','comment','--comment',marker,'-j','ACCEPT'],['FORWARD','-i','vmbr0','-o','vmbr110','-d','10.110.0.0/24','-m','conntrack','--ctstate','ESTABLISHED,RELATED','-m','comment','--comment',marker,'-j','ACCEPT']]
def rule(r,op):
 i=2 if r[:1]==['-t'] else 0
 return ['iptables',*r[:i],op,*r[i:]]
import shlex
text='# '+marker+' private nested guest network\nauto vmbr110\niface vmbr110 inet static\n    address 10.110.0.1/24\n    bridge-ports none\n    bridge-stp off\n    bridge-fd 0\n'
for r in rules:
 text+='    post-up '+shlex.join(rule(r,'-C'))+' || '+shlex.join(rule(r,'-A'))+'\n'
 text+='    post-down '+shlex.join(rule(r,'-D'))+' || true\n'
p=pathlib.Path('/etc/network/interfaces.d/opendeploy-tiny10')
if p.exists() and not p.read_text().startswith('# '+marker+' '):raise RuntimeError('Network file belongs to another configuration')
p.write_text(text)
p=pathlib.Path('/etc/sysctl.d/90-opendeploy-tiny10-forward.conf')
if p.exists() and not p.read_text().startswith('# '+marker+'\n'):raise RuntimeError('Forwarding file belongs to another configuration')
p.write_text('# '+marker+'\nnet.ipv4.ip_forward=1\n')
subprocess.run(['sysctl','-w','net.ipv4.ip_forward=1'],check=True)
for r in rules:
 if subprocess.run(rule(r,'-C'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:subprocess.run(rule(r,'-A'),check=True)
p=job/'guest-selection.json';v=json.loads(p.read_text());v['vm']['bridge']='vmbr110';tmp=p.with_suffix('.json.new');tmp.write_text(json.dumps(v));os.replace(tmp,p)
print('Persisted owned private bridge and scoped guest NAT; original plan unchanged')
PY
