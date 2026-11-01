"""Restore exact original media bytes from the original base and sealed differences.

The final deliverables are complete encrypted ISO/VDI files, not patch files.
Original private plan/key data is never written into repository files or logs.
No file digest is computed; public base and static relay data are reused.
"""
import json
import os
import pathlib
import shutil
import struct
import subprocess
import tarfile
import urllib.request
import zipfile
from cryptography.hazmat.primitives import serialization,padding
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

root=pathlib.Path(__file__).parent
private=pathlib.Path('/workspace/work/relay55/private/media-reconstruction')
private.mkdir(mode=0o700,exist_ok=True)
os.chmod(private,0o700)
for name in ['prepared-media-delta.zip.aes','media-key-envelope.bin']:
    request=urllib.request.Request('https://filebin.net/opendeploy-final-delta-20261027/'+name,headers={'Cookie':'verified=2024-05-24'})
    with urllib.request.urlopen(request,timeout=30) as response,(private/name).open('wb') as dest:
        shutil.copyfileobj(response,dest)
transport=serialization.load_pem_private_key(pathlib.Path('/workspace/work/relay55/private/delivery-transport-private.pem').read_bytes(),password=None)
envelope=transport.decrypt((private/'media-key-envelope.bin').read_bytes(),rsa_padding.PKCS1v15())
if len(envelope)!=96:raise RuntimeError('Unexpected private envelope format')
key=envelope[:32]
encrypted=(private/'prepared-media-delta.zip.aes').read_bytes()
header=encrypted[:32]
decryptor=Cipher(algorithms.AES(key),modes.CBC(header[16:32])).decryptor()
unpadder=padding.PKCS7(128).unpadder()
plain=unpadder.update(decryptor.update(encrypted[32:])+decryptor.finalize())+unpadder.finalize()
if len(plain)!=struct.unpack('<Q',header[8:16])[0]:raise RuntimeError('Incomplete sealed difference archive')
delta=private/'differences.zip';delta.write_bytes(plain)

with zipfile.ZipFile(root/'base-runtime.zip') as base,zipfile.ZipFile(delta) as changes:
    layout=json.loads(changes.read('media-layout.json'))
    reference=private/'public-relay-reference.bin'
    with base.open('assets/linux-x64.tar.gz') as stream,tarfile.open(fileobj=stream,mode='r|gz') as archive,reference.open('wb') as dest:
        for member in archive:
            if member.isfile():
                with archive.extractfile(member) as source:shutil.copyfileobj(source,dest,1024*1024)
    reference_info=json.loads(changes.read('reference.json'))
    if reference.stat().st_size!=reference_info['reference_bytes']:raise RuntimeError('Static reference source differs')
    compressed=private/'iso.patch.zst';compressed.write_bytes(changes.read('iso.patch.zst'))
    patch=private/'iso.patch'
    subprocess.run(['zstd','-d','--no-check','-M512MB','--patch-from='+str(reference),'-f',str(compressed),'-o',str(patch)],check=True)
    if patch.stat().st_size!=reference_info['changes_bytes']:raise RuntimeError('Original byte-difference stream is incomplete')
    iso=private/'OpenDeploy-PXVIRT-Original-20261025.iso'
    with base.open('assets/pxvirt-8.4-2-amd64.iso') as source,iso.open('wb') as dest:shutil.copyfileobj(source,dest,1024*1024)
    with iso.open('r+b') as target,patch.open('rb') as source:
        target.truncate(layout['iso_bytes'])
        while block:=source.read(12):
            if len(block)!=12:raise RuntimeError('Incomplete byte-difference record')
            offset,size=struct.unpack('<QI',block);data=source.read(size)
            if len(data)!=size or offset+size>layout['iso_bytes']:raise RuntimeError('Original byte-difference bounds differ')
            target.seek(offset);target.write(data)
    vdi=private/'OpenDeploy-Prepared-Media-32G-20261025.vdi'
    with vdi.open('wb') as target:
        target.write(changes.read('vdi.header'));target.truncate(layout['vdi_bytes'])
    with vdi.open('r+b') as target,iso.open('rb') as source:
        block_size=layout['vdi_block_bytes'];extra=layout['vdi_block_extra']
        for virtual,physical in enumerate(layout['vdi_blocks']):
            if physical in (0xffffffff,0xfffffffe):continue
            source.seek(virtual*block_size);data=source.read(block_size).ljust(block_size,b'\0')
            target.seek(layout['vdi_data_offset']+physical*(block_size+extra)+extra);target.write(data)
    residual=changes.read('vdi.patch')
    if residual:raise RuntimeError('This original disk requires residual records; use the general byte-patch restoration')

output=root/'media-parts';output.mkdir(exist_ok=True)
manifest={'artifacts':[]}
for kind,source,original_header in [('ISO',iso,envelope[32:64]),('PreparedDisk',vdi,envelope[64:96])]:
    if original_header[:8]!=b'ODISO1\r\n' or struct.unpack('<Q',original_header[8:16])[0]!=source.stat().st_size:raise RuntimeError('Original sealed-media header differs')
    target=private/(source.name+'.aes')
    encryptor=Cipher(algorithms.AES(key),modes.CBC(original_header[16:32])).encryptor();padder=padding.PKCS7(128).padder()
    with source.open('rb') as src,target.open('wb') as dst:
        dst.write(original_header)
        while block:=src.read(8*1024*1024):dst.write(encryptor.update(padder.update(block)))
        dst.write(encryptor.update(padder.finalize())+encryptor.finalize())
    artifact={'kind':kind,'name':target.name,'bytes':target.stat().st_size,'parts':[]}
    with target.open('rb') as src:
        index=0
        while block:=src.read(16*1024*1024):
            name=target.name+'.part'+str(index).zfill(3);(output/name).write_bytes(block)
            artifact['parts'].append({'name':name,'bytes':len(block)});index+=1
    manifest['artifacts'].append(artifact)
    print(json.dumps({'kind':kind,'original_bytes':source.stat().st_size,'encrypted_bytes':target.stat().st_size,'parts':index}),flush=True)
(root/'sealed-media-delivery.json').write_text(json.dumps(manifest,indent=2))
