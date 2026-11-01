"""Extract exact byte differences for the already-created ISO and installer VDI.

No installation, disk mount, source changes, or file digests. The delta contains
private deployment data and must be sealed before any network transfer.
"""
import json
import io
import pathlib
import struct
import sys
import zipfile

root=pathlib.Path(r'I:\xxm\PXVIRT-Trial-20261021\dev\Delivery-20261027')
sys.path.insert(0,str(root/'parser'))
from dissect.hypervisor.disk.vdi import VDI
from dissect.volume.disk import Disk
from dissect.ntfs import NTFS

class ExactVDIReader(io.RawIOBase):
    """Respect every dynamic VDI block mapping, including multi-block reads."""
    def __init__(self, image):
        self.image=image;self.raw=image.fh;self.position=0
        self.raw.seek(image.blocks_offset)
        self.blocks=struct.unpack('<'+'I'*image.number_of_blocks,self.raw.read(4*image.number_of_blocks))
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        position=offset+(self.position if whence==1 else self.image.size if whence==2 else 0)
        if position<0:raise ValueError('Negative VDI position')
        self.position=position;return position
    def read(self,size=-1):
        left=max(0,self.image.size-self.position)
        size=left if size<0 else min(size,left)
        result=bytearray()
        while size:
            index,within=divmod(self.position,self.image.block_size)
            take=min(size,self.image.block_size-within)
            block=self.blocks[index]
            if block in (0xffffffff,0xfffffffe):data=b'\0'*take
            else:
                extra=self.image.header.cbBlockExtra
                self.raw.seek(self.image.data_offset+block*(self.image.block_size+extra)+extra+within)
                data=self.raw.read(take)
                if len(data)!=take:raise IOError('Original VDI block is incomplete')
            result.extend(data);self.position+=take;size-=take
        return bytes(result)
    def readinto(self,buffer):
        data=self.read(len(buffer));buffer[:len(data)]=data;return len(data)

private=root/'private-export'
iso=private/'OpenDeploy-PXVIRT-Original-20261025.iso'
vdi_path=pathlib.Path(r'I:\xxm\PXVIRT-Trial-20261021\dev\vm\PXVIRT-Repo-Debug-20261022\Debug-Install-Media-32G.vdi')
original_windows=vdi_path.with_name('Initial-Windows-80G.vdi')
chunk=64*1024
report={'iso_bytes':iso.stat().st_size,'vdi_bytes':vdi_path.stat().st_size,'block_bytes':chunk}
target=private/'prepared-media-delta.zip'

def record(dest,offset,data):
    dest.write(struct.pack('<QI',offset,len(data)));dest.write(data)

with original_windows.open('rb') as raw, vdi_path.open('rb') as vdi_raw:
    disk=Disk(ExactVDIReader(VDI(raw)))
    fs=NTFS(next(p for p in disk.partitions if p.offset==554696704).open())
    original_iso=fs.mft.get('PXVIRT-OneFolder/Job-PXVIRTOnly-v2/media/OpenDeploy-PXVIRT.iso')
    exact=iso.with_suffix('.iso.exact')
    with original_iso.open() as source, exact.open('wb') as output:
        while data:=source.read(4*1024*1024):output.write(data)
    if exact.stat().st_size!=original_iso.size():raise IOError('Original ISO extraction is incomplete')
    exact.replace(iso)
    prepared=iso.open('rb')
    with zipfile.ZipFile(fs.mft.get('PXVIRT-OneFolder/original-runtime.zip').open()) as original, zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as delta:
        base_info=original.getinfo('assets/pxvirt-8.4-2-amd64.iso')
        report['base_iso_bytes']=base_info.file_size
        changed=0;offset=0
        with original.open(base_info) as base, delta.open('iso.patch','w',force_zip64=True) as patch:
            while data:=prepared.read(chunk):
                before=base.read(len(data))
                if data!=before:record(patch,offset,data);changed+=len(data)
                offset+=len(data)
        report['iso_changed_bytes']=changed
        media=VDI(vdi_raw)
        header=media.header
        report.update(vdi_data_offset=media.data_offset,vdi_block_bytes=media.block_size,vdi_block_extra=header.cbBlockExtra,vdi_block_count=media.number_of_blocks)
        vdi_raw.seek(0);delta.writestr('vdi.header',vdi_raw.read(media.data_offset))
        vdi_raw.seek(media.blocks_offset)
        blocks=struct.unpack('<'+'I'*media.number_of_blocks,vdi_raw.read(4*media.number_of_blocks))
        report['vdi_blocks']=list(blocks)
        residual=0
        with delta.open('vdi.patch','w',force_zip64=True) as patch:
            for virtual,physical in enumerate(blocks):
                if physical in (0xffffffff,0xfffffffe):continue
                physical_offset=media.data_offset+physical*(media.block_size+header.cbBlockExtra)
                if header.cbBlockExtra:
                    vdi_raw.seek(physical_offset);extra=vdi_raw.read(header.cbBlockExtra)
                    if any(extra):record(patch,physical_offset,extra);residual+=len(extra)
                for within in range(0,media.block_size,chunk):
                    take=min(chunk,media.block_size-within)
                    vdi_raw.seek(physical_offset+header.cbBlockExtra+within);actual=vdi_raw.read(take)
                    prepared.seek(virtual*media.block_size+within);expected=prepared.read(take)
                    expected=expected.ljust(take,b'\0')
                    if actual!=expected:record(patch,physical_offset+header.cbBlockExtra+within,actual);residual+=len(actual)
        report['vdi_residual_bytes']=residual
        delta.writestr('media-layout.json',json.dumps(report))
report.pop('vdi_blocks')
report['delta_zip_bytes']=target.stat().st_size
(root/'delta-status.json').write_text(json.dumps(report))
print(json.dumps(report),flush=True)
