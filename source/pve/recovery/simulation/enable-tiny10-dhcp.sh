set -e
python3 - <<'PY'
import pathlib,json,subprocess
j=pathlib.Path('/opt/opendeploy');p=json.loads((j/'plan.json').read_text());marker='OpenDeploy-'+p['id']
c=dict(l.split(': ',1) for l in subprocess.check_output(['qm','config','110'],text=True).splitlines() if ': ' in l)
assert c['description']==marker and 'uuid='+p['vm']['uuid'] in c['smbios1'] and c['net0']=='e1000=BC:24:11:D5:1C:15,bridge=vmbr110'
conf=j/'tiny10-dhcp.conf'
conf.write_text('# '+marker+'\nport=0\ninterface=vmbr110\nbind-interfaces\nno-resolv\nno-hosts\nuser=root\ndhcp-range=10.110.0.0,static,255.255.255.0,12h\ndhcp-host=BC:24:11:D5:1C:15,10.110.0.10,tiny10,infinite\ndhcp-ignore=tag:!known\ndhcp-option=option:router,10.110.0.1\ndhcp-option=option:dns-server,10.0.2.3\ndhcp-authoritative\nlog-dhcp\ndhcp-leasefile=/opt/opendeploy/tiny10-dhcp.leases\n')
unit=pathlib.Path('/etc/systemd/system/opendeploy-tiny10-dhcp.service')
if unit.exists() and marker not in unit.read_text():raise RuntimeError('DHCP unit has other ownership')
unit.write_text('[Unit]\nDescription='+marker+' private Tiny10 DHCP\nAfter=networking.service\n[Service]\nType=simple\nExecStart=/usr/sbin/dnsmasq --keep-in-foreground --conf-file=/opt/opendeploy/tiny10-dhcp.conf --pid-file=\nRestart=on-failure\nRestartSec=5\n[Install]\nWantedBy=multi-user.target\n')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','--now','opendeploy-tiny10-dhcp.service'],check=True)
print('Enabled DHCP only for owned Tiny10 MAC on private vmbr110')
PY
