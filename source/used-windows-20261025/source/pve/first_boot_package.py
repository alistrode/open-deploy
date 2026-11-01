"""Deterministic first-boot service package missing from pinned PXVIRT 8.4-2.

This is OpenDeploy's compatibility implementation, not an upstream binary.
Builds with the bundled Python on Windows as well as on Linux.
"""
import gzip
import io
import pathlib
import tarfile

NAME = 'proxmox-first-boot_0.1+opendeploy1_all.deb'
UNIT_PATH = 'lib/systemd/system/proxmox-first-boot-multi-user.service'
UNIT = '''[Unit]
Description=OpenDeploy verified installation first boot
Wants=network-online.target
After=network-online.target pve-cluster.service ssh.service
ConditionPathExists=/var/lib/proxmox-first-boot/pending-first-boot-setup
StartLimitIntervalSec=0

[Service]
Type=oneshot
User=root
TimeoutStartSec=infinity
ExecStart=/var/lib/proxmox-first-boot/proxmox-first-boot
ExecStartPost=/bin/rm -f /var/lib/proxmox-first-boot/pending-first-boot-setup
RemainAfterExit=yes
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
'''
CONTROL = '''Package: proxmox-first-boot
Version: 0.1+opendeploy1
Architecture: all
Maintainer: OpenDeploy project
Depends: systemd, bash, coreutils
Section: admin
Priority: optional
Description: OpenDeploy first-boot compatibility service for PXVIRT 8.4-2
 Supplies the multi-user service required by the pinned installer when
 first-boot ordering is fully-up. Implementation belongs to OpenDeploy.
'''


def archive(files):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for name, content in files.items():
            data = content.encode('utf-8')
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.uid = info.gid = info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    data = gzip.compress(raw.getvalue(), mtime=0)
    # Python 3.11/3.12 otherwise inherits zlib's platform-specific gzip OS byte.
    return data[:9] + b'\xff' + data[10:]


def build(path):
    members = {'debian-binary': b'2.0\n',
               'control.tar.gz': archive({'control': CONTROL}),
               'data.tar.gz': archive({UNIT_PATH: UNIT})}
    out = bytearray(b'!<arch>\n')
    for name, data in members.items():
        out.extend(f'{name + "/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(data):<10}`\n'.encode('ascii'))
        out.extend(data)
        if len(data) % 2:
            out.extend(b'\n')
    pathlib.Path(path).write_bytes(out)

