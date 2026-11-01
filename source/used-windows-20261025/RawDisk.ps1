# Query the opened physical handle instead of FileStream.Length (not a regular file).
if (!('OpenDeployRawDisk' -as [type])) {
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class OpenDeployRawDisk {
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool DeviceIoControl(SafeFileHandle h, uint code, byte[] input, int ilen,
        byte[] output, int olen, out int returned, IntPtr overlapped);
    public static long Length(SafeFileHandle h) {
        var data=new byte[8]; int count;
        if(!DeviceIoControl(h,0x7405c,null,0,data,data.Length,out count,IntPtr.Zero) || count<8)
            throw new Win32Exception(Marshal.GetLastWin32Error());
        return BitConverter.ToInt64(data,0);
    }
    public static string UsbSerial(SafeFileHandle h) {
        var input=new byte[12];var data=new byte[4096];int count;
        if(!DeviceIoControl(h,0x2d1400,input,input.Length,data,data.Length,out count,IntPtr.Zero) || count<36)
            throw new Win32Exception(Marshal.GetLastWin32Error());
        if(BitConverter.ToUInt32(data,28)!=7) throw new InvalidOperationException("Handle is not USB storage");
        int offset=checked((int)BitConverter.ToUInt32(data,24));
        if(offset<36 || offset>=count) throw new InvalidOperationException("USB handle has no serial");
        int end=offset;while(end<count && data[end]!=0)end++;
        return System.Text.Encoding.ASCII.GetString(data,offset,end-offset).Trim();
    }
}
'@
}
