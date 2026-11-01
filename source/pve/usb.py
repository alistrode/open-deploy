"""Explicitly bound Linux USB writer. Never discovers a target by disk number."""
import fcntl
import json
import os
import pathlib
import stat
import struct
import subprocess


def command(args):
    return subprocess.check_output(args,text=True).strip()


def binding(device):
    path=pathlib.Path(device)
    if not str(path).startswith('/dev/disk/by-id/usb-') or not path.is_symlink():
        raise ValueError('USB target must be an existing /dev/disk/by-id/usb-* identity')
    if not stat.S_ISBLK(path.stat().st_mode):raise ValueError('USB target is not a block device')
    props=dict(line.split('=',1) for line in command(['udevadm','info','--query=property','--name',str(path)]).splitlines() if '=' in line)
    if props.get('ID_BUS')!='usb' or not props.get('ID_SERIAL_SHORT'):raise ValueError('USB transport and exact serial are required')
    kind=command(['lsblk','--noheadings','--output','TYPE',str(path)]).splitlines()[0].strip()
    if kind!='disk':raise ValueError('Select the whole USB disk, not a partition')
    return {'path':str(path),'serial':props['ID_SERIAL_SHORT'],'bytes':int(command(['blockdev','--getsize64',str(path)]))}


def unmount(device):
    data=json.loads(command(['lsblk','--json','--paths','--output','NAME,MOUNTPOINTS',device]))
    mounts=[]
    def walk(node):
        points=[x for x in node.get('mountpoints',[]) if x]
        if any(x in ['/','/boot','/boot/efi','[SWAP]'] for x in points):raise ValueError('USB contains a running system or swap; refused')
        mounts.extend(points)
        for child in node.get('children',[]):walk(child)
    for node in data['blockdevices']:walk(node)
    for mountpoint in sorted(set(mounts),key=len,reverse=True):subprocess.run(['umount',mountpoint],check=True)


def write(image,spec):
    image=pathlib.Path(image)
    if not image.is_file():raise ValueError('Prepared image is missing; USB untouched')
    if binding(spec['path'])!=spec:raise ValueError('USB identity or capacity changed; USB untouched')
    unmount(spec['path'])
    fd=os.open(spec['path'],os.O_RDWR|os.O_EXCL)
    try:
        # An open block handle stays attached to this device if it is unplugged.
        if not stat.S_ISBLK(os.fstat(fd).st_mode) or binding(spec['path'])!=spec:raise ValueError('USB changed while opening')
        capacity=struct.unpack('Q',fcntl.ioctl(fd,0x80081272,bytes(8)))[0]
        if capacity!=spec['bytes'] or image.stat().st_size>capacity:raise ValueError('USB capacity mismatch')
        def output(block):
            view=memoryview(block)
            while view:
                n=os.write(fd,view)
                if n<=0:raise OSError('Short USB write')
                view=view[n:]
        # Remove an old end-of-disk GPT backup outside the new ISO image.
        if capacity>image.stat().st_size+1024*1024:
            os.lseek(fd,capacity-1024*1024,os.SEEK_SET);output(bytes(1024*1024))
        os.lseek(fd,0,os.SEEK_SET)
        with image.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):output(chunk)
        os.fsync(fd)
    finally:os.close(fd)
    return {'serial':spec['serial'],'image_bytes':image.stat().st_size,
            'write_completed':True}

