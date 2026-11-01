param([Parameter(Mandatory)][int]$DiskNumber)
$ErrorActionPreference='Stop'
if(!('OpenDeployNvmeIdentity' -as [type])) {
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using System.ComponentModel;
public static class OpenDeployNvmeIdentity {
 [DllImport("kernel32.dll",SetLastError=true)]static extern bool DeviceIoControl(SafeFileHandle h,uint code,byte[] input,int ilen,byte[] output,int olen,out int count,IntPtr overlapped);
 static void Put(byte[] b,int offset,uint value){Array.Copy(BitConverter.GetBytes(value),0,b,offset,4);}
 public static string[] Read(int number){
  using(var disk=new FileStream(@"\\.\PhysicalDrive"+number,FileMode.Open,FileAccess.Read,FileShare.ReadWrite)){
   // STORAGE_PROPERTY_QUERY + STORAGE_PROTOCOL_SPECIFIC_DATA, NVMe CNS=1.
   foreach(uint property in new uint[]{49,50}){
    byte[] query=new byte[4144],answer=new byte[4144];int returned;
    Put(query,0,property);Put(query,8,3);Put(query,12,1);Put(query,16,1);Put(query,24,40);Put(query,28,4096);
    if(!DeviceIoControl(disk.SafeFileHandle,0x2d1400,query,query.Length,answer,answer.Length,out returned,IntPtr.Zero))continue;
    int offset=8+checked((int)BitConverter.ToUInt32(answer,24));
    if(offset<48||offset+64>returned)continue;
    string serial=Encoding.ASCII.GetString(answer,offset+4,20).Trim(' ','\0');
    string model=Encoding.ASCII.GetString(answer,offset+24,40).Trim(' ','\0');
    if(serial.Length>0&&model.Length>0)return new string[]{serial,model};
   }
   throw new InvalidOperationException("The actual NVMe controller serial could not be read; no serial was guessed.");
  }
 }
}
'@
}
$disk=Get-Disk -Number $DiskNumber
if($disk.BusType -eq 'NVMe') {
    $identity=[OpenDeployNvmeIdentity]::Read($DiskNumber)
    @{number=$DiskNumber;serial=$identity[0];model=$identity[1];source='NVMe Identify Controller';unique_id=[string]$disk.UniqueId;size=[long]$disk.Size}
} else {
    $serial=([string]$disk.SerialNumber).Trim()
    if(!$serial -or $serial -match '^[0_\.]+$'){throw 'This disk does not report a usable unique serial; it was not selected automatically.'}
    @{number=$DiskNumber;serial=$serial;model=[string]$disk.FriendlyName;source='Storage device serial';unique_id=[string]$disk.UniqueId;size=[long]$disk.Size}
}
