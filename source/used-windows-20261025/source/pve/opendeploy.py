#!/usr/bin/env python3
"""PXVIRT three-stage deployment. Real execution only on the explicitly bound host."""
import argparse
import base64
import contextlib
import hashlib
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent
RULES = json.loads((ROOT / 'workflow.json').read_text())
RELAY_SHA = '59c1716194a3e2bbaa2cdce9fa84ed3463b0ab1c77f7d1640874a4448a50deda'
ISO_ASSETS = frozenset(('pxvirt', 'windows', 'virtio', 'seed'))


def is_iso(path):
    return str(path).lower().endswith(('.iso', '.iso.partial'))


def asset_record(path, *, iso=False):
    path = pathlib.Path(path)
    result = {'path': str(path), 'bytes': path.stat().st_size}
    if not iso and not is_iso(path):
        result['sha256'] = sha(path)
    return result


def asset_present(item, *, iso=False):
    path = pathlib.Path(item['path'])
    if not path.is_file():
        return False
    if 'bytes' in item and path.stat().st_size != item['bytes']:
        return False
    return True if iso or is_iso(path) else sha(path) == item['sha256']


def sha(path):
    if is_iso(path):
        raise ValueError('ISO hashing is prohibited by user instruction')
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as stream:
        for b in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def atomic(path, value):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.new')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(value, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    if os.name == 'posix':
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def call(args, *, timeout=120, check=True):
    arguments = [str(x) for x in args[1:]]
    if os.name == 'nt' and args[0] in ['xorriso', 'ssh-keygen', 'openssl']:
        for index, value in enumerate(arguments):
            if re.match(r'^[A-Za-z]:[\\/]', value):
                converted = subprocess.run([str(program('cygpath')), '-u', value], capture_output=True,
                                           text=True, encoding='utf-8', check=True, timeout=30)
                arguments[index] = converted.stdout.strip()
    p = subprocess.run([str(program(args[0]))] + arguments, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if check and p.returncode:
        # Never echo commands or answer-file contents containing passwords.
        raise RuntimeError(f'{args[0]} failed ({p.returncode}): {p.stderr[-1500:]}')
    return p


def program(name):
    if os.name == 'nt':
        bundle = ROOT.parent.parent
        if name == 'wimlib-imagex':
            return bundle / 'wimlib/wimlib-imagex.exe'
        if name in ['xorriso', 'ssh-keygen', 'openssl', 'cygpath']:
            return bundle / 'runtime/usr/bin' / (name + '.exe')
    return name


def plan_digest(p):
    return hashlib.sha256(json.dumps(p, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load(path):
    p = json.loads(pathlib.Path(path).read_text(encoding='utf-8-sig'))
    if p.get('schema') != 1 or p.get('relay_version') != '3.0':
        raise ValueError('Expected schema 1 and relay 3.0; version 4.0 is prohibited')
    uuid.UUID(p['id'])
    for name in ['name', 'storage', 'bridge', 'iso_storage']:
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,62}', p['vm'][name]):
            raise ValueError('Invalid VM option: ' + name)
    for key, lo, hi in [('vmid', 100, 999999999), ('cores', 1, 128), ('memory_mb', 2048, 1048576), ('disk_gb', 32, 65536)]:
        if type(p['vm'][key]) is not int or not lo <= p['vm'][key] <= hi:
            raise ValueError('Invalid VM sizing: ' + key)
    if type(p['vm']['image_index']) is not int or p['vm']['image_index'] < 1:
        raise ValueError('Windows image index must be a positive integer')
    for name, item in p['assets'].items():
        if name == 'relay' and is_iso(item['path']):
            raise ValueError('Relay must be the pinned archive, not an ISO')
        if name in ISO_ASSETS or is_iso(item['path']):
            continue  # Legacy ISO digest fields are never read or compared.
        if not re.fullmatch('[0-9a-f]{64}', item['sha256']):
            raise ValueError('Invalid asset SHA-256')
    if not p.get('guest_media_mode') == 'deferred' and p['assets']['relay']['sha256'] != RELAY_SHA:
        raise ValueError('Unapproved relay bytes')
    # Exact serial, not a device number or a glob matching multiple physical disks.
    if not p['host']['disk_serial'] or any(c in p['host']['disk_serial'] for c in '*?[]\n\r'):
        raise ValueError('An exact target disk serial is required')
    return p


class Journal:
    def __init__(self, path, plan):
        self.path = pathlib.Path(path)
        self.hash = plan_digest(plan)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {'plan_sha256': self.hash, 'phase': 'configured', 'events': []}
        if self.data['plan_sha256'] != self.hash:
            raise ValueError('Plan changed after configuration; use a new job')

    def advance(self, action, facts):
        rule = next((r for r in RULES['transitions'] if r['action'] == action and r['from'] == self.data['phase']), None)
        if not rule or not set(rule['requires']) <= set(facts):
            raise ValueError('Transition rejected: ' + action)
        self.data['phase'] = rule['to']
        self.data['events'].append({'action': action, 'facts': sorted(facts), 'at': int(time.time())})
        atomic(self.path, self.data)


@contextlib.contextmanager
def locked(path):
    if os.name == 'nt':
        import msvcrt
        with open(str(path) + '.lock', 'a+b') as stream:
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl
    fd = os.open(str(path) + '.lock', os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def verify_assets(p):
    for name, item in p['assets'].items():
        if not asset_present(item, iso=name in ISO_ASSETS):
            raise ValueError('Missing or changed asset: ' + name)


def iso_boot_info(path):
    r=call(['xorriso','-indev',path,'-report_system_area','cmd','-report_el_torito','plain'])
    text=r.stdout+r.stderr
    match=re.search(r"^-volume_date uuid '?([0-9]+)'?",text,re.M)
    platforms=set(re.findall(r'El Torito boot img\s*:\s*\d+\s+(BIOS|UEFI)',text))
    if not match or platforms!={'BIOS','UEFI'}:raise ValueError('Expected a hybrid BIOS/UEFI PXVIRT installation ISO')
    return match.group(1),platforms


def patch_boot_menu(text):
    # PXVIRT 8.4-2's GRUB label was renamed, but unconfigured.sh still
    # accepts only proxauto/proxmox-start-auto-installer. Preserve the title.
    old='Pxvirt-start-auto-installer'
    if text.count(old)!=2:raise ValueError('Unexpected community installer boot menu; inspect instead of guessing')
    return text.replace(old,'proxmox-start-auto-installer')


def configure(args):
    target = pathlib.Path(args.job).resolve()
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = target / 'plan.json'
    if path.exists():
        raise ValueError('Job already configured; existing plan retained')
    assets = {}
    for key in ['pxvirt', 'relay']:
        value = pathlib.Path(getattr(args, key)).resolve()
        assets[key] = asset_record(value, iso=key in ISO_ASSETS)
    p = {'schema': 1, 'id': str(uuid.uuid4()), 'relay_version': '3.0', 'host': {'disk_serial': args.disk_serial.strip(), 'fqdn': 'opendeploy.home.arpa'},
         'vm': {'vmid': 110, 'name': 'tiny10', 'cores': 4, 'memory_mb': 8192, 'disk_gb': 100, 'storage': 'local-lvm', 'iso_storage': 'local', 'bridge': 'vmbr0', 'uuid': str(uuid.uuid4()), 'image_index': args.image_index, 'language': 'en-US'},
         'media_layout': 'pxvirt-only-v1', 'assets': assets, 'windows_user': 'operator', 'windows_password': secrets.token_urlsafe(24), 'host_password': secrets.token_urlsafe(32)}
    if args.usb_device:
        from usb import binding
        p['usb']=binding(args.usb_device)
    atomic(path, p)
    try:
        load(path)
    except Exception:
        path.unlink()
        raise
    atomic(target / 'state.json', {'plan_sha256': plan_digest(p), 'phase': 'configured', 'events': []})
    for stage, command in [('1-Prepare', 'prepare'), ('2-Install-Win10', 'install'), ('3-Finalize', 'finalize')]:
        launcher = target / (stage + '.sh')
        import shlex
        launcher.write_text('#!/bin/sh\nset -eu\nexec python3 ' + shlex.quote(str(ROOT / 'opendeploy.py')) + ' ' + command + ' --job ' + shlex.quote(str(target)) + '\n', encoding='utf-8', newline='\n')
        launcher.chmod(0o700)
    print(json.dumps({'configured': True, 'job': str(target), 'relay_version': '3.0'}))


def native_windows_iso(script, iso):
    """Use the Windows filesystem reader, including images with an empty ISO9660 tree."""
    encoded_path = base64.b64encode(str(pathlib.Path(iso).resolve()).encode('utf-8')).decode('ascii')
    prefix = "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';" \
             "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);" \
             "Import-Module (Join-Path $PSHOME 'Modules\\Storage\\Storage.psd1');" \
             "$path=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded_path + "'));"
    encoded = base64.b64encode((prefix + script).encode('utf-16le')).decode('ascii')
    powershell = pathlib.Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, text=True, encoding='utf-8-sig', errors='replace', timeout=120)
    if result.returncode:
        raise RuntimeError('Native Windows ISO inspection failed: ' + result.stderr[-1500:])
    return result.stdout


@contextlib.contextmanager
def native_windows_install_image(iso):
    # This is a read-only OS mount, not a hypervisor ISO attachment. Never
    # unmount an image that the user had already mounted before this operation.
    mounted = json.loads(native_windows_iso(r'''
$disk=Get-DiskImage -ImagePath $path
$owned=$false
try {
    if(!$disk.Attached){$disk=Mount-DiskImage -ImagePath $path -StorageType ISO -Access ReadOnly -PassThru;$owned=$true}
    $volumes=@($disk|Get-Volume)
    $image=$null
    foreach($name in @('install.wim','install.esd')){
        $matches=@(foreach($volume in $volumes){
            $root=if($volume.DriveLetter){$volume.DriveLetter+':\'}else{$volume.Path}
            if($root){$candidate=Join-Path $root ('sources\'+$name);if(Test-Path -LiteralPath $candidate -PathType Leaf){$candidate}}
        })
        if($matches.Count -gt 1){throw 'Windows installation image is ambiguous'}
        if($matches.Count -eq 1){$image=$matches[0];break}
    }
    if(!$image){throw 'Windows ISO must contain sources/install.wim or install.esd'}
    @{path=$image;owned=$owned}|ConvertTo-Json -Compress
}catch{
    if($owned){Dismount-DiskImage -ImagePath $path -ErrorAction SilentlyContinue|Out-Null}
    throw
}
''', iso))
    try:
        yield pathlib.Path(mounted['path'])
    finally:
        if mounted['owned']:
            native_windows_iso('Dismount-DiskImage -ImagePath $path|Out-Null', iso)


def image_language(image, index):
    # --xml renders through the terminal code page on Windows. Extract the
    # original XML bytes instead, preserving the WIM's Unicode encoding.
    with tempfile.TemporaryDirectory(prefix='opendeploy-wim-meta-') as directory:
        metadata = pathlib.Path(directory) / 'image.xml'
        result = subprocess.run([str(program('wimlib-imagex')), 'info', str(image),
                                 '--extract-xml=' + str(metadata)], capture_output=True, timeout=120)
        if result.returncode or not metadata.is_file():
            raise ValueError('Cannot read Windows image metadata')
        root = ET.fromstring(metadata.read_bytes())
    found = next((item for item in root.findall('IMAGE') if item.get('INDEX') == str(index)), None)
    if found is None or found.findtext('WINDOWS/ARCH') != '9':
        raise ValueError('Selected Windows image must exist and be x64')
    language = found.findtext('WINDOWS/LANGUAGES/DEFAULT')
    if not language or not re.fullmatch('[a-z]{2,3}-[A-Za-z0-9-]+', language):
        raise ValueError('Cannot determine Windows image language')
    return language


def windows_language(iso, index):
    """Inspect the actual WIM/ESD; do not guess Tiny10's language or index."""
    if os.name == 'nt':
        with native_windows_install_image(iso) as image:
            return image_language(image, index)
    with tempfile.TemporaryDirectory(prefix='opendeploy-wim-') as directory:
        image=None
        for name in ['install.wim','install.esd']:
            path=pathlib.Path(directory)/name
            result=call(['xorriso','-osirrox','on','-indev',iso,'-extract','/sources/'+name,path],timeout=600,check=False)
            if result.returncode==0 and path.is_file():image=path;break
        if image is None:raise ValueError('Windows ISO must contain sources/install.wim or install.esd')
        return image_language(image, index)


def unattended(p):
    ns = 'urn:schemas-microsoft-com:unattend'
    ET.register_namespace('', ns)
    ET.register_namespace('wcm', 'http://schemas.microsoft.com/WMIConfig/2002/State')
    root = ET.Element('{'+ns+'}unattend')
    def node(parent, tag, text=None, **attrs):
        e = ET.SubElement(parent, '{'+ns+'}'+tag, attrs)
        if text is not None:
            e.text = str(text)
        return e
    def component(parent, name):
        return node(parent, 'component', name=name, processorArchitecture='amd64', publicKeyToken='31bf3856ad364e35', language='neutral', versionScope='nonSxS')
    def locale(settings,name):
        intl=component(settings,name)
        language=p['vm'].get('language','en-US')
        if name.endswith('-WinPE'):node(node(intl,'SetupUILanguage'),'UILanguage',language)
        for field in ['InputLocale','SystemLocale','UILanguage','UserLocale']:node(intl,field,language)
    pe = node(root, 'settings', pass_='windowsPE')
    pe.attrib = {'pass': 'windowsPE'}
    locale(pe,'Microsoft-Windows-International-Core-WinPE')
    setup = component(pe, 'Microsoft-Windows-Setup')
    disks = node(setup, 'DiskConfiguration')
    disk = node(disks, 'Disk', **{'{http://schemas.microsoft.com/WMIConfig/2002/State}action':'add'})
    node(disk, 'DiskID', 0)
    node(disk, 'WillWipeDisk', 'true')
    parts = node(disk, 'CreatePartitions')
    for order, size in [(1, 500), (2, None)]:
        part = node(parts, 'CreatePartition', **{'{http://schemas.microsoft.com/WMIConfig/2002/State}action':'add'})
        node(part, 'Order', order); node(part, 'Type', 'Primary')
        node(part, 'Size' if size else 'Extend', size if size else 'true')
    mods = node(disk, 'ModifyPartitions')
    for order in [1, 2]:
        part = node(mods, 'ModifyPartition', **{'{http://schemas.microsoft.com/WMIConfig/2002/State}action':'add'})
        node(part, 'Order', order); node(part, 'PartitionID', order); node(part, 'Format', 'NTFS')
        if order == 1:
            node(part, 'Active', 'true'); node(part, 'Label', 'System')
        else:
            node(part, 'Letter', 'C'); node(part, 'Label', 'Windows')
    node(disks, 'WillShowUI', 'OnError')
    image = node(node(setup, 'ImageInstall'), 'OSImage')
    meta = node(node(image, 'InstallFrom'), 'MetaData', **{'{http://schemas.microsoft.com/WMIConfig/2002/State}action':'add'})
    node(meta, 'Key', '/IMAGE/INDEX'); node(meta, 'Value', p['vm']['image_index'])
    dest = node(image, 'InstallTo'); node(dest, 'DiskID', 0); node(dest, 'PartitionID', 2)
    node(image, 'WillShowUI', 'OnError')
    node(node(setup, 'UserData'), 'AcceptEula', 'true')
    spec = node(root, 'settings', **{'pass': 'specialize'})
    shell = component(spec, 'Microsoft-Windows-Shell-Setup')
    node(shell, 'ComputerName', 'TINY10-AI'); node(shell, 'TimeZone', 'China Standard Time')
    deploy = component(spec, 'Microsoft-Windows-Deployment')
    commands = node(deploy, 'RunSynchronous')
    cmd = node(commands, 'RunSynchronousCommand', **{'{http://schemas.microsoft.com/WMIConfig/2002/State}action':'add'})
    node(cmd, 'Order', 1)
    # Seed is attached to this VM only; no network download during Windows setup.
    ps = "$ErrorActionPreference='Stop';$s=@(Get-Volume|Where-Object {$_.DriveLetter -and (Test-Path ($_.DriveLetter+':\\OpenDeploy\\Guest-Finalize.ps1'))});if($s.Count -ne 1){throw 'Deployment seed missing or ambiguous'};Copy-Item ($s[0].DriveLetter+':\\OpenDeploy') C:\\OpenDeploy -Recurse -Force; & C:\\OpenDeploy\\Guest-Finalize.ps1 -Bootstrap"
    import base64
    node(cmd, 'Path', 'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand ' + base64.b64encode(ps.encode('utf-16le')).decode())
    oobe = node(root, 'settings', **{'pass':'oobeSystem'})
    locale(oobe,'Microsoft-Windows-International-Core')
    shell = component(oobe, 'Microsoft-Windows-Shell-Setup')
    ob = node(shell, 'OOBE')
    for name, val in [('HideEULAPage','true'),('HideOnlineAccountScreens','true'),('HideWirelessSetupInOOBE','true'),('ProtectYourPC','3')]:node(ob,name,val)
    accounts = node(node(shell, 'UserAccounts'), 'LocalAccounts')
    account = node(accounts, 'LocalAccount', **{'{http://schemas.microsoft.com/WMIConfig/2002/State}action':'add'})
    node(account, 'Name', p['windows_user']); node(account, 'Group', 'Administrators')
    password = node(account, 'Password'); node(password, 'Value', p['windows_password']); node(password, 'PlainText', 'true')
    return ET.tostring(root, encoding='unicode', xml_declaration=True)


def host_answer(p):
    q = json.dumps
    # The pinned ISO predates the kebab-case global password keys. Hash via
    # stdin so neither the command line nor installer parse errors reveal it.
    result=subprocess.run([str(program('openssl')),'passwd','-6','-salt',uuid.UUID(p['id']).hex[:16],'-stdin'],
                          input=(p['host_password']+'\n').encode('utf-8'),capture_output=True,timeout=15)
    # Text pipes on Windows translate LF to CRLF. MSYS OpenSSL would hash the
    # extra CR, making both root SSH and PAM API login reject the saved password.
    password_hash=result.stdout.decode('ascii').strip()
    if result.returncode or not password_hash.startswith('$6$'):raise ValueError('Cannot hash host password')
    return f'''[global]
keyboard = "en-us"
country = "cn"
fqdn = {q(p['host']['fqdn'])}
mailto = "root@localhost.localdomain"
timezone = "Asia/Shanghai"
root_password_hashed = {q(password_hash)}
[first-boot]
source = "from-iso"
ordering = "fully-up"
[network]
source = "from-dhcp"
[disk-setup]
filesystem = "ext4"
filter.ID_SERIAL_SHORT = {q(p['host']['disk_serial'])}
'''


def init_relay(job, payload):
    """Generate host/AI keys offline. The deployed far and AI retain the same identity."""
    import base64
    data = payload / 'relay-state'
    data.mkdir(mode=0o700, exist_ok=True)
    near = job / 'ai-private'
    near.mkdir(mode=0o700, exist_ok=True)
    for path in [data/'host_key', near/'client_key']:
        if not path.exists():call(['ssh-keygen','-q','-t','ed25519','-N','','-f',path])
    public = (data/'host_key.pub').read_text().split()
    host_public = ' '.join(public[:2])
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(public[1])).digest()).decode().rstrip('=')
    existing = data/'connection-private.json'
    if existing.exists():
        info = json.loads(existing.read_text())
    else:
        info = {'version':1,'target':'linux','broker':'wss://broker.emqx.io:8084/mqtt','session':secrets.token_hex(16),
                'secret':secrets.token_hex(32),'user':'relay','fingerprint':fingerprint,'hostPublicKey':host_public,
                'clientPrivateKey':(near/'client_key').read_text()}
        atomic(existing,info)
    config = {k:v for k,v in info.items() if k not in ['clientPrivateKey','hostPublicKey']}
    config['sshPort']=0
    atomic(data/'remote.json',config)
    shutil.copyfile(near/'client_key.pub',data/'client_key.pub')
    atomic(near/'connection-private.json',info)
    atomic(near/'near.json',{k:info[k] for k in ['broker','session','secret','user','fingerprint']} | {'localPort':0,'statusPath':str(near/'peer.json')})
    (near/'known_hosts').write_text('opendeploy-pve '+host_public+'\n', encoding='utf-8', newline='\n')
    (near/'known_hosts').chmod(0o600)


def check_installed_disk(p):
    if os.geteuid()!=0 or not pathlib.Path('/etc/pve').is_dir():raise ValueError('Bootstrap requires installed PXVIRT root')
    source=call(['findmnt','--noheadings','--output','SOURCE','/']).stdout.strip()
    serials=call(['lsblk','--inverse','--noheadings','--output','SERIAL',source]).stdout.splitlines()
    if p['host']['disk_serial'] not in [s.strip() for s in serials]:
        raise ValueError('Installed system disk does not match the prepared target serial')


def register(job,p,j):
    check_installed_disk(p)
    for name in ['opendeploy-stage2.service','opendeploy-relay.service','opendeploy-portal.service','opendeploy-guest.service']:
        shutil.copy2(job/'templates'/name,pathlib.Path('/etc/systemd/system')/name)
    call(['systemctl','daemon-reload'])
    call(['systemctl','enable','--now','--no-block','opendeploy-stage2.service'])
    print('Stage two registered for automatic execution and retry')


def bootstrap(job,p,j):
    check_installed_disk(p)
    # Host binding cannot be replaced merely by rerunning a later stage.
    machine=pathlib.Path('/etc/machine-id').read_text().strip()
    if j.data.get('host_machine_id') not in [None,machine]:raise ValueError('Host binding changed')
    target=pathlib.Path('/var/lib/opendeploy/relay3')
    if target.exists():
        if sha(target/'host_key') != sha(job/'relay-state/host_key'):raise ValueError('Existing relay identity differs; retained')
    else:
        shutil.copytree(job/'relay-state',target)
        target.chmod(0o700)
    shutil.copy2(job/'templates/opendeploy-relay.service','/etc/systemd/system/opendeploy-relay.service')
    call(['systemctl','daemon-reload'])
    call(['systemctl','enable','--now','opendeploy-relay.service'])
    j.data['host_machine_id']=machine
    atomic(j.path,j.data)
    if j.data['phase']=='media_ready':j.advance('host.done',{'host_bound','relay_running'})
    for name,command in [('2-Install-Win10.sh','install'),('3-Finalize.sh','finalize')]:
        path=job/name
        path.write_text('#!/bin/sh\nset -eu\nexec python3 /opt/opendeploy/opendeploy.py '+command+' --job /opt/opendeploy\n', encoding='utf-8', newline='\n')
        path.chmod(0o700)
    call(['systemctl','enable','--now','opendeploy-portal.service'])
    print('PXVIRT ready. Open Continue-PXVIRT.cmd on the preparation computer to choose guest media.')


def prepare(job, p, j):
    if p.get('media_layout') != 'pxvirt-only-v1':
        raise ValueError('This job uses the old bundled guest media layout. Choose a new job directory; old progress was retained.')
    if (job/'media.json').exists():
        receipt=json.loads((job/'media.json').read_text())
        finish_media(job,p,j,receipt)
        print('Media already prepared; continuing without rebuilding')
        return
    if j.data['phase'] != 'configured':
        raise ValueError('Media receipt missing')
    media = job / 'media'
    media.mkdir(mode=0o700, exist_ok=True)
    payload = media / 'payload'
    payload.mkdir(mode=0o700, exist_ok=True)
    for legacy in ['windows.iso','virtio.iso','seed.iso']:
        (payload/legacy).unlink(missing_ok=True)
    shutil.rmtree(media/'seed',ignore_errors=True)
    # Keep all application dependencies and locked runtime; no desktop is launched.
    with tarfile.open(p['assets']['relay']['path']) as tar:
        tar.extractall(payload / 'relay', filter='data')
    for pattern in ['*.py','*.cjs']:
        for f in ROOT.glob(pattern):shutil.copy2(f, payload / f.name)
    shutil.copy2(ROOT / 'workflow.json', payload / 'workflow.json')
    shutil.copytree(ROOT / 'templates', payload / 'templates', dirs_exist_ok=True)
    # Installer media is private: passwords and the exact target binding live here.
    host_plan = json.loads(json.dumps(p))
    for name, item in host_plan['assets'].items():
        if name in ISO_ASSETS or is_iso(item['path']):
            item.pop('sha256', None)
    # Guest media is selected only after PXVIRT is running. No guest ISO or seed
    # belongs on the host installation medium, including legacy plan inputs.
    host_plan['assets'] = {}
    host_plan['guest_media_mode'] = 'deferred'
    init_relay(job, payload)
    portal = {'token': secrets.token_urlsafe(32), 'port': 8007}
    if (job/'portal-access.json').exists():
        portal = json.loads((job/'portal-access.json').read_text())
    atomic(job/'portal-access.json', portal)
    atomic(payload/'portal-access.json', portal)
    atomic(payload / 'plan.json', host_plan)
    atomic(payload / 'state.json', {'plan_sha256':plan_digest(host_plan), 'phase':'media_ready', 'events':[]})
    hook = (ROOT / 'templates/first-boot.sh').read_text().replace('__PLAN_ID__',p['id'])
    (media/'first-boot.sh').write_text(hook, encoding='utf-8', newline='\n'); (media/'first-boot.sh').chmod(0o700)
    (media/'answer.toml').write_text(host_answer(p), encoding='utf-8', newline='\n'); (media/'answer.toml').chmod(0o600)
    (media/'auto-installer-mode.toml').write_text('mode = "iso"\n[http]\n', encoding='utf-8', newline='\n')
    # PXVIRT 8.4-2's installer calls setup_proxmox_first_boot_service before
    # generating initramfs/GRUB, but its ISO omits the required service package.
    # Include our deterministic compatibility package in the installer's own
    # package directory so normal dpkg installation supplies the missing unit.
    from first_boot_package import NAME as first_boot_name, build as build_first_boot
    first_boot_deb = media / first_boot_name
    build_first_boot(first_boot_deb)
    original_grub=media/'original-grub.cfg'
    if original_grub.exists():original_grub.unlink()
    call(['xorriso','-osirrox','on','-indev',p['assets']['pxvirt']['path'],'-extract','/boot/grub/grub.cfg',original_grub])
    (media/'grub.cfg').write_text(patch_boot_menu(original_grub.read_text()), encoding='utf-8', newline='\n')
    out = media/'OpenDeploy-PXVIRT.iso'
    if out.exists():raise ValueError('Partial media exists; inspect it before rebuilding in a fresh job')
    # Append to a copied hybrid image, as the installer assistant does. A full
    # replay fails for PXVIRT's overlapping hybrid GPT/APM partition layout.
    iso_uuid,platforms=iso_boot_info(p['assets']['pxvirt']['path'])
    partial=out.with_suffix('.iso.partial')
    shutil.copyfile(p['assets']['pxvirt']['path'],partial)
    call(['xorriso','-boot_image','any','keep','-volume_date','uuid',iso_uuid,'-dev',partial,
          '-map',media/'answer.toml','/answer.toml','-map',media/'auto-installer-mode.toml','/auto-installer-mode.toml',
          '-map',media/'first-boot.sh','/proxmox-first-boot','-map',payload,'/opendeploy',
          '-map',media/'grub.cfg','/boot/grub/grub.cfg',
          '-map',first_boot_deb,'/proxmox/packages/'+first_boot_name,
          '-chmod','0755','/proxmox-first-boot'],timeout=1800)
    os.replace(partial,out)
    receipt = {'outputs':[asset_record(out, iso=True)], 'physical_write_performed':False}
    atomic(job/'media.json',receipt)
    finish_media(job,p,j,receipt)
    print(json.dumps(receipt))


def finish_media(job,p,j,receipt):
    # New receipts never perpetuate legacy ISO digest fields.
    receipt['outputs'] = [asset_record(item['path'], iso=True) for item in receipt['outputs']]
    if 'usb' in p:
        from usb import write
        item=receipt['outputs'][0]
        if not receipt.get('physical_write_performed'):
            receipt['usb']=write(item['path'],p['usb'])
        receipt['physical_write_performed']=True
        atomic(job/'media.json',receipt)
    if j.data['phase']=='configured':j.advance('media.done',{'inputs_verified','boot_preserved'})


class Host:
    def __init__(self,p):self.p=p;self.v=p['vm'];self.vmid=str(self.v['vmid'])
    def qm(self,*args,**kw):return call(['qm',*args],**kw)
    def bind(self,j):
        if os.geteuid()!=0 or not pathlib.Path('/etc/pve').is_dir():raise ValueError('Run this stage as root on installed PXVIRT')
        # Exact machine-id persists across reboots; reinstall requires an explicit new host binding.
        machine=pathlib.Path('/etc/machine-id').read_text().strip()
        if j.data.get('host_machine_id')!=machine:raise ValueError('Host identity differs from first-boot binding')
        if not pathlib.Path('/sys/class/net',self.v['bridge']).is_dir():raise ValueError('VM network bridge missing')
        if not pathlib.Path('/dev/kvm').exists():raise ValueError('KVM unavailable; verify firmware VT-x before creating the Windows VM')
    def config(self):
        p=self.qm('config',self.vmid,check=False)
        if p.returncode:
            if 'does not exist' in p.stderr:return None
            raise RuntimeError('Cannot inspect VM configuration: ' + p.stderr[-500:])
        return dict(line.split(': ',1) for line in p.stdout.splitlines() if ': ' in line)
    def owned(self):
        c=self.config()
        if not c or c.get('description')!='OpenDeploy-'+self.p['id']:raise ValueError('VM is absent or not owned by this plan')
        if ('uuid='+self.v['uuid']) not in c.get('smbios1',''):raise ValueError('VM identity mismatch')
        return c
    def volume(self,key):
        item=self.p['assets'][key]
        if item.get('volume'):
            return item['volume']
        path=pathlib.Path(item['path'])
        if not asset_present(item, iso=True):raise ValueError('Asset missing or size changed: '+key)
        storage=self.v['iso_storage']
        dest=f'{storage}:iso/od-{self.p["id"]}-{key}.iso'
        target=pathlib.Path(call(['pvesm','path',dest]).stdout.strip())
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.is_file() or target.stat().st_size != path.stat().st_size:
            tmp=target.with_suffix('.partial');shutil.copyfile(path,tmp)
            if tmp.stat().st_size != path.stat().st_size:raise ValueError('Staged ISO size differs')
            os.replace(tmp,target)
        return dest
    def status(self):
        return self.qm('status',self.vmid).stdout.strip().split()[-1]
    def guest(self):
        self.owned()
        # Receipt read is synchronous and has a real exit code; agent ping alone is insufficient.
        script="[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ErrorActionPreference='Stop';$p=Get-Content C:\\OpenDeploy\\ready.json -Raw|ConvertFrom-Json;$u=(Get-CimInstance Win32_ComputerSystemProduct).UUID;$s=(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Setup\\State').ImageState;if($s -ne 'IMAGE_STATE_COMPLETE'){exit 3};@{id=$p.id;uuid=$u;completed=$p.completed}|ConvertTo-Json -Compress"
        import base64
        result=self.qm('guest','exec',self.vmid,'--timeout','60','--','powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode(),timeout=80)
        report=json.loads(result.stdout)
        if not report.get('exited') or report.get('exitcode')!=0:raise ValueError('Guest verification command not successful')
        d=json.loads(report['out-data'].lstrip('\ufeff'))
        if d.get('id')!=self.p['id'] or str(d.get('uuid','')).lower()!=self.v['uuid'].lower() or d.get('completed') is not True:
            raise ValueError('Guest receipt or machine identity mismatch')
        return d
    def wait_guest(self,seconds):
        end=time.monotonic()+seconds
        while True:
            try:return self.guest()
            except (ValueError,RuntimeError,subprocess.TimeoutExpired):
                if time.monotonic()>=end:raise
                time.sleep(5)
    def snapshots(self):
        return json.loads(self.qm('listsnapshot',self.vmid,'--output-format','json').stdout)
    def stable(self):
        marker='OpenDeploy-'+self.p['id']
        return any(s['name']=='od-stable' and s.get('description')==marker for s in self.snapshots())
    def rdp(self):
        shutil.copy2(ROOT/'templates/opendeploy-rdp.service','/etc/systemd/system/opendeploy-rdp.service')
        call(['systemctl','daemon-reload'])
        call(['systemctl','enable','--now','opendeploy-rdp.service'])


def guest_plan(job, plan):
    selection = job/'guest-selection.json'
    if not selection.exists():
        raise ValueError('Choose Tiny10 and VirtIO media in the OpenDeploy page after PXVIRT is ready')
    selected = json.loads(selection.read_text())
    result = json.loads(json.dumps(plan))
    result['assets'] = selected['assets']
    result['vm'].update(selected['vm'])
    return result


def select_guest_media(job, plan, journal, windows, virtio, image_index=1):
    if journal.data['phase'] != 'host_ready':
        raise ValueError('Guest media can only be selected after PXVIRT is ready and before VM creation')
    if type(image_index) is not int or image_index < 1:
        raise ValueError('Choose a positive Windows image index')
    assets = {}
    for key, volume in [('windows', windows), ('virtio', virtio)]:
        # A configured PXVIRT ISO storage includes local and shared storage.
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*:iso/[^/\\]+\.iso', volume, re.I) or '..' in volume:
            raise ValueError('Choose an ISO from PXVIRT storage or upload it first')
        path = call(['pvesm', 'path', volume]).stdout.strip()
        assets[key] = asset_record(path, iso=True) | {'volume': volume}
    missing = [pkg for tool,pkg in [('xorriso','xorriso'),('wimlib-imagex','wimtools')] if not shutil.which(tool)]
    if missing:
        call(['apt-get','update'],timeout=600)
        call(['apt-get','install','--yes',*missing],timeout=900)
    updated = json.loads(json.dumps(plan))
    updated['vm']['image_index'] = image_index
    updated['vm']['language'] = windows_language(assets['windows']['path'], image_index)
    seed = job/'guest-seed'
    (seed/'OpenDeploy').mkdir(parents=True, exist_ok=True)
    (seed/'Autounattend.xml').write_text(unattended(updated), encoding='utf-8', newline='\n')
    shutil.copy2(ROOT/'templates/Guest-Finalize.ps1', seed/'OpenDeploy/Guest-Finalize.ps1')
    atomic(seed/'OpenDeploy/guest-plan.json', {'id':plan['id'], 'uuid':plan['vm']['uuid']})
    partial = job/'guest-seed.iso.partial'
    call(['xorriso','-as','mkisofs','-J','-r','-V','ODSEED','-o',partial,seed])
    os.replace(partial, job/'guest-seed.iso')
    assets['seed'] = asset_record(job/'guest-seed.iso', iso=True)
    atomic(job/'guest-selection.json', {'assets':assets, 'vm':{'image_index':image_index, 'language':updated['vm']['language']}})


def install(job,p,j):
    p = guest_plan(job, p)
    h=Host(p);h.bind(j)
    if j.data['phase'] in ['installing','guest_ready','snapshotting','complete']:
        h.owned();print('VM already created; installation is not replayed');return
    if j.data['phase']=='host_ready':
        if h.config() is not None:raise ValueError('VMID already exists; existing VM retained')
        for key in ['windows','virtio','seed']:h.volume(key)
        j.advance('vm.intent',{'host_bound','vmid_free','inputs_verified'})
    if j.data['phase']!='vm_creating':raise ValueError('Stage two requires first-boot host_ready')
    if h.config() is None:
        iso={k:h.volume(k) for k in ['windows','virtio','seed']}
        h.qm('create',h.vmid,'--name',h.v['name'],'--description','OpenDeploy-'+p['id'],
             '--smbios1','uuid='+h.v['uuid'],'--machine','pc','--bios','seabios','--ostype','win10',
             '--cores',h.v['cores'],'--memory',h.v['memory_mb'],'--balloon','0','--cpu','host','--vga','std',
             '--sata0',f'{h.v["storage"]}:{h.v["disk_gb"]}',
             '--ide0',iso['virtio']+',media=cdrom','--ide1',iso['seed']+',media=cdrom','--ide2',iso['windows']+',media=cdrom',
             '--net0','e1000,bridge='+h.v['bridge'],'--agent','enabled=1','--boot','order=sata0;ide2','--onboot','1',timeout=180)
    c=h.owned()
    expected={'cores':str(h.v['cores']),'memory':str(h.v['memory_mb']),'ostype':'win10','bios':'seabios'}
    if any(c.get(k)!=v for k,v in expected.items()) or 'sata0' not in c or not all(k in c for k in ['ide0','ide1','ide2']):
        raise ValueError('Interrupted VM creation is incomplete; inspect owned VM without allocating another disk')
    if h.status()!='running':h.qm('start',h.vmid,timeout=180)
    j.advance('vm.done',{'host_bound','vm_owned','vm_configured'})
    print('Win10 installer started; stage three waits for actual guest completion')


def finalize(job,p,j,wait):
    if j.data['phase'] == 'complete':
        print('Deployment already complete; no additional verification or replay')
        return
    p = guest_plan(job, p)
    h=Host(p);h.bind(j);h.owned()
    if j.data['phase'] == 'installing':
        # Wait for the installer's completion signal, not a separate acceptance run.
        h.wait_guest(wait)
        j.advance('guest.done',{'vm_owned','guest_bound','guest_healthy'})
    if j.data['phase'] != 'guest_ready':
        raise ValueError('Guest installation must finish before remote configuration')
    h.rdp()
    j.advance('deployment.done',{'vm_owned','remote_configured'})
    print('Guest installation and remote configuration complete')


def restore(job,p,j,wait):
    h=Host(p);h.bind(j);h.owned()
    if not h.stable():raise ValueError('Verified stable snapshot required')
    if j.data['phase']=='complete':j.advance('recover.intent',{'vm_owned','snapshot_verified'})
    if j.data['phase']!='recovering':raise ValueError('No completed deployment to restore')
    # Reapplying the same stable disk snapshot is an explicit recovery operation.
    if h.status()!='stopped':h.qm('stop',h.vmid,timeout=120)
    h.qm('rollback',h.vmid,'od-stable',timeout=300)
    h.qm('start',h.vmid,timeout=180);h.wait_guest(wait)
    j.advance('recover.done',{'vm_owned','guest_bound','guest_healthy'})
    finalize(job,p,j,wait)


def main():
    a=argparse.ArgumentParser(description=__doc__);sub=a.add_subparsers(dest='command',required=True)
    c=sub.add_parser('configure');c.add_argument('--job',required=True)
    for key in ['pxvirt','relay','disk-serial']:c.add_argument('--'+key,required=True)
    c.add_argument('--image-index',type=int,default=1)
    c.add_argument('--usb-device',help='Optional exact /dev/disk/by-id/usb-* identity, written only by stage one')
    for name in ['prepare','register','bootstrap','install','finalize','restore','status']:
        s=sub.add_parser(name);s.add_argument('--job',default='/opt/opendeploy');s.add_argument('--wait',type=int,default=1800)
    args=a.parse_args()
    if args.command=='configure':return configure(args)
    job=pathlib.Path(args.job).resolve();p=load(job/'plan.json')
    with locked(job/'state.json'):
        j=Journal(job/'state.json',p)
        if args.command=='prepare':prepare(job,p,j)
        elif args.command=='register':register(job,p,j)
        elif args.command=='bootstrap':bootstrap(job,p,j)
        elif args.command=='install':install(job,p,j)
        elif args.command=='finalize':finalize(job,p,j,args.wait)
        elif args.command=='restore':restore(job,p,j,args.wait)
        else:print(json.dumps({'phase':j.data['phase'],'relay_version':p['relay_version'],'vmid':p['vm']['vmid']}))


if __name__=='__main__':
    try:main()
    except Exception as e:
        print(str(e),file=sys.stderr);sys.exit(1)
