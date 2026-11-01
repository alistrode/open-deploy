"""One destructive write/read pass for the explicitly bound 2GB OpenDeploy USB.
Only run after the existing full raw image and installer files have been preserved.
Uses aligned unbuffered Windows I/O; never selects a disk by drive letter.
"""
import argparse,ctypes,ctypes.wintypes as w,hashlib,json,pathlib,subprocess,time,traceback
ap=argparse.ArgumentParser();ap.add_argument('--receipt',required=True);ap.add_argument('--block-bytes',type=int,choices=(1048576,4194304),default=1048576);a=ap.parse_args()
receipt=pathlib.Path(a.receipt); receipt.parent.mkdir(parents=True,exist_ok=True)
SIZE=2013265920; BLOCK=a.block_bytes
PS="""$d=Get-Disk -Number 2;$c=Get-CimInstance Win32_DiskDrive | Where-Object Index -eq 2; [PSCustomObject]@{number=$d.Number;name=$d.FriendlyName;size=[long]$d.Size;bus=[string]$d.BusType;boot=$d.IsBoot;system=$d.IsSystem;readonly=$d.IsReadOnly;pnp=$c.PNPDeviceID} | ConvertTo-Json -Compress"""
EXPECTED_PNP=r'USBSTOR\DISK&VEN_GENERAL&PROD_UDISK&REV_5.00\6&2E4EBCDF&0&_&0'
identity=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-Command',PS],text=True))
assert identity['number']==2 and identity['name'].strip()=='General UDisk' and identity['size']==SIZE and identity['bus']=='USB'
assert not any(identity[k] for k in ('boot','system','readonly')) and identity['pnp'].upper()==EXPECTED_PNP
state={'state':'starting','identity':identity,'expected_bytes':SIZE,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'written_bytes':0,'verified_bytes':0,'io':'unbuffered/write-through','block_bytes':BLOCK,'success':False}
t0=time.monotonic()
def save(**kw):
 state.update(kw);state['elapsed_seconds']=round(time.monotonic()-t0,1)
 temp=receipt.with_suffix('.tmp');temp.write_text(json.dumps(state,indent=2),encoding='utf-8');temp.replace(receipt)
 print(json.dumps({k:state[k] for k in ('state','written_bytes','verified_bytes','elapsed_seconds')}),flush=True)
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE];k.CreateFileW.restype=w.HANDLE
k.VirtualAlloc.argtypes=[ctypes.c_void_p,ctypes.c_size_t,w.DWORD,w.DWORD];k.VirtualAlloc.restype=ctypes.c_void_p
k.VirtualFree.argtypes=[ctypes.c_void_p,ctypes.c_size_t,w.DWORD]
k.WriteFile.argtypes=[w.HANDLE,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.c_void_p]
k.ReadFile.argtypes=k.WriteFile.argtypes
k.CloseHandle.argtypes=[w.HANDLE];k.FlushFileBuffers.argtypes=[w.HANDLE]
k.DeviceIoControl.argtypes=[w.HANDLE,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.c_void_p]
INVALID=ctypes.c_void_p(-1).value
buf=None;h=None
seed=bytes.fromhex('a39216ce485550baca7b6229d4458ffdf06d35cca83ff63706410f00f4dd6229')
def pattern(off,n):return hashlib.shake_256(seed+off.to_bytes(8,'little')).digest(n)
def opened(access):
 h=k.CreateFileW(r'\\.\PhysicalDrive2',access,3,None,3,0xA0000000,None)
 if h==INVALID:raise ctypes.WinError(ctypes.get_last_error())
 n=w.DWORD();length=ctypes.c_longlong()
 if not k.DeviceIoControl(h,0x7405c,None,0,ctypes.byref(length),8,ctypes.byref(n),None):raise ctypes.WinError(ctypes.get_last_error())
 if length.value!=SIZE:raise RuntimeError('Physical handle size changed')
 return h
try:
 buf=k.VirtualAlloc(None,BLOCK,0x3000,4)
 if not buf:raise ctypes.WinError(ctypes.get_last_error())
 save(state='writing')
 h=opened(0xC0000000)
 for off in range(0,SIZE,BLOCK):
  n=min(BLOCK,SIZE-off);data=pattern(off,n);ctypes.memmove(buf,data,n);done=w.DWORD()
  if not k.WriteFile(h,buf,n,ctypes.byref(done),None):raise ctypes.WinError(ctypes.get_last_error())
  if done.value!=n:raise RuntimeError(f'Short write at {off}: {done.value}/{n}')
  state['written_bytes']=off+n
  if state['written_bytes']%(64*1024*1024)==0:save()
 if not k.FlushFileBuffers(h):raise ctypes.WinError(ctypes.get_last_error())
 k.CloseHandle(h);h=None
 save(state='verifying')
 h=opened(0x80000000)
 for off in range(0,SIZE,BLOCK):
  n=min(BLOCK,SIZE-off);done=w.DWORD()
  if not k.ReadFile(h,buf,n,ctypes.byref(done),None):raise ctypes.WinError(ctypes.get_last_error())
  data=ctypes.string_at(buf,done.value);expected=pattern(off,n)
  if data!=expected:
   first=next((i for i,(x,y) in enumerate(zip(data,expected)) if x!=y),len(data))
   raise RuntimeError(f'Readback mismatch at byte {off+first}; read {done.value}, expected {n}')
  state['verified_bytes']=off+n
  if state['verified_bytes']%(64*1024*1024)==0:save()
 save(state='passed',success=True)
except BaseException as e:
 save(state='failed',error=f'{type(e).__name__}: {e}');raise
finally:
 if h is not None and h!=INVALID:k.CloseHandle(h)
 if buf:k.VirtualFree(buf,0,0x8000)
