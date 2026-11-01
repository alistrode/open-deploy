"""Read-only acceptance probe; run on the disposable PXVIRT test host."""
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=30).stdout.strip()


def main():
    job = pathlib.Path('/opt/opendeploy')
    unit = 'proxmox-first-boot-multi-user.service'
    status = dict(line.split('=', 1) for line in command('systemctl', 'show', unit,
                  '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result').splitlines())
    complete = (status.get('ActiveState') == 'active' and status.get('SubState') == 'exited'
                and status.get('Result') == 'success'
                and not pathlib.Path('/var/lib/proxmox-first-boot/pending-first-boot-setup').exists())
    facts = {'root_ssh_authenticated': os.geteuid() == 0 and bool(os.environ.get('SSH_CONNECTION')), 'first_boot': status,
             'first_boot_complete': complete,
             'services': {name:command('systemctl','is-active',name)
                          for name in ['ssh','pveproxy','pvedaemon','pve-cluster']}}
    if complete:
        plan = json.loads((job / 'plan.json').read_text())
        spec = importlib.util.spec_from_file_location('host_health', job / 'host_health.py')
        health = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(health)
        # Verify only: do not call health.main(), pvecm or reload services.
        facts.update(health.verify_api(plan, timeout=30))
        facts['kernel'] = command('uname','-r')
        facts['pveversion'] = command('pveversion')
        facts['root_source'] = command('findmnt','-n','-o','SOURCE','/')
        facts['disk_serials'] = command('lsblk','-dn','-o','SERIAL').splitlines()
        facts['initrd_present'] = bool(list(pathlib.Path('/boot').glob('initrd.img-*')))
        facts['grub_config_present'] = pathlib.Path('/boot/grub/grub.cfg').is_file()
        facts['first_boot_package'] = command('dpkg-query','-W','-f=${Version}', 'proxmox-first-boot')
        names = ['opendeploy.py','first_boot_package.py','host_health.py','relay-supervisor.cjs',
                 'templates/opendeploy-stage2.service','templates/first-boot.sh','workflow.json']
        facts['runtime_sha256'] = {name:hashlib.sha256((job/name).read_bytes()).hexdigest()
                                   for name in names}
        facts['journal_phase'] = json.loads((job/'state.json').read_text())['phase']
        facts['public_relay_ready_marker'] = pathlib.Path('/var/lib/opendeploy/relay3/opendeploy-ready.json').exists()
    facts['accepted'] = (complete and facts['root_ssh_authenticated'] and facts.get('api_ready') is True
                         and facts.get('tls_verified') is True
                         and all(value == 'active' for value in facts['services'].values())
                         and facts.get('initrd_present') and facts.get('grub_config_present'))
    print(json.dumps(facts, indent=2))


if __name__ == '__main__':
    main()
