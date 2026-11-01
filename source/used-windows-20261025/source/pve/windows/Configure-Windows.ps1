param([string]$Job = (Join-Path $env:LOCALAPPDATA 'OpenDeploy\PXVIRT-job-v2'))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
function Choose-Disk([string]$Title, $Disks) {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = $Title
    $form.Width = 850; $form.Height = 220; $form.StartPosition = 'CenterScreen'
    $list = New-Object System.Windows.Forms.ComboBox
    $list.Left = 15; $list.Top = 25; $list.Width = 790
    $list.DropDownStyle = 'DropDownList'
    $items = @($Disks)
    foreach ($disk in $items) {
        [void]$list.Items.Add(('Disk {0}: {1}, {2:N0} GiB, serial={3}' -f $disk.Number,$disk.FriendlyName,($disk.Size/1GB),$disk.SerialNumber.Trim()))
    }
    $button = New-Object System.Windows.Forms.Button
    $button.Text = 'Select'; $button.Top = 85; $button.Left = 350
    $button.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.Controls.Add($list); $form.Controls.Add($button); $form.AcceptButton = $button
    if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK -or $list.SelectedIndex -lt 0) { throw 'Disk selection cancelled' }
    return $items[$list.SelectedIndex]
}
$simulation = [System.Windows.Forms.MessageBox]::Show('Use a dedicated virtual disk as the installation medium inside the designated VirtualBox guest?', 'OpenDeploy deployment mode', [System.Windows.Forms.MessageBoxButtons]::YesNo) -eq [System.Windows.Forms.DialogResult]::Yes
if ($simulation -and (Get-CimInstance Win32_ComputerSystem).Model -notmatch 'VirtualBox') { throw 'Simulation mode is restricted to a VirtualBox guest' }
$all = @(Get-Disk | Where-Object { $_.SerialNumber -and $_.SerialNumber.Trim() })
$target = Choose-Disk 'PXVIRT target disk: this disk will be ERASED during installation' @($all | Where-Object { !$_.IsBoot -and !$_.IsSystem })
$usb = Choose-Disk 'Installation USB: this USB disk will be ERASED now' @($all | Where-Object { ($simulation -or $_.BusType -eq 'USB') -and !$_.IsBoot -and !$_.IsSystem -and $_.Number -ne $target.Number })
if (@($all | Where-Object { $_.SerialNumber.Trim() -eq $target.SerialNumber.Trim() }).Count -ne 1) { throw 'Target serial is not unique' }
New-Item -ItemType Directory -Path $Job -Force | Out-Null
@{schema=1; target_disk_serial=$target.SerialNumber.Trim(); usb_serial=$usb.SerialNumber.Trim(); simulation=$simulation} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Job 'windows-settings.json') -Encoding UTF8
