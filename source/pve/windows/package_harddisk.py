"""Build one complete PXVIRT hard-disk-ISO USB tool delivery (standard library only)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

README = '''OpenDeploy：完整 PXVIRT 安装 U 盘工具包

实体机准备入口：START-HARDDISK-USB.cmd。
VirtualBox 克隆机入口：START-VM.cmd，参数和前提见 docs/DELIVERY.md。
虚拟机入口默认只制作介质；显式传入 -RestartToMedia 才安排启动安装。
这个入口不会重启或安装系统。发现现有 media_ready 状态时只显示状态，不改文件。

完整解压整个 OpenDeploy 文件夹即可，不能只取其中几个文件。
包内已包含源码、Python、Windows 工具依赖、原连接程序归档、引导资源和交接文档，
不需要另外下载补丁或手工拼文件。

当前远端的准备已经完成，不需要重复运行。下一位 AI 请先读 docs/HANDOFF.md。
用户当前明确要求先别装机；不要设置下一次 USB 启动、重启或清盘。

程序目录与现场数据分开：镜像留在 E:\\OpenDeploy-PXVIRT.iso；
原配置和原连接身份留在现有作业目录以及 F:\\OpenDeploy-private。
这些现场私密数据不打进仓库发布包，也不能因替换程序而删除或重新生成。

当前现场由已有远控的 SYSTEM 账号调用入口，读取同一账号的原作业目录。
你不需要手工选盘、填表、合并文件或复制命令。
当前现场已采用分段内存引导，不要绕过此入口重复运行旧做盘脚本覆盖它。\n完整包不是在任意新电脑免配置装机的通用镜像；换机器由 AI 先完成对应配置和权限准备。

更多信息：docs/HANDOFF.md（当前事实、版本、已完成/剩余步骤和交接），
docs/DELIVERY.md（完整交付内容和部署方法），docs/DESIGN.md（项目设计）。
'''


def build(source, runtime, output, application_commit):
    source, runtime, output = Path(source).resolve(), Path(runtime).resolve(), Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns('__pycache__', '*.pyc')
    with tempfile.TemporaryDirectory(prefix='.complete-delivery-', dir=output.parent) as work:
        bundle = Path(work)/'OpenDeploy'
        bundle.mkdir()
        for name in ('python', 'runtime', 'boot-assets'):
            shutil.copytree(runtime/name, bundle/name, ignore=ignore)
        if (runtime/'runtime-provenance.json').is_file():
            shutil.copyfile(runtime/'runtime-provenance.json', bundle/'runtime-provenance.json')
        (bundle/'assets').mkdir()
        shutil.copyfile(runtime/'assets/linux-x64.tar.gz', bundle/'assets/linux-x64.tar.gz')
        shutil.copytree(source/'source/pve', bundle/'source/pve', ignore=ignore)
        shutil.copytree(source/'docs', bundle/'docs', ignore=ignore)
        shutil.copytree(source/'.agents', bundle/'.agents', ignore=ignore)
        if (source/'private-recovery/README.md').is_file():
            (bundle/'private-recovery').mkdir()
            shutil.copyfile(source/'private-recovery/README.md', bundle/'private-recovery/README.md')
        for name in ('Start-Windows.ps1', 'Start-VM.ps1', 'Write-Usb.ps1', 'RawDisk.ps1',
                     'Boot-Media.ps1', 'Configure-Windows.ps1', 'Continue-PXVIRT.ps1', 'Continue-PXVIRT.cmd'):
            shutil.copyfile(source/'source/pve/windows'/name, bundle/name)
        (bundle/'START-VM.cmd').write_bytes(
            b'@echo off\r\nsetlocal\r\npowershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0Start-VM.ps1" %*\r\nexit /b %errorlevel%\r\n')
        command = (
            '$ErrorActionPreference="Stop"; $root=$env:OD_COMPLETE_BUNDLE; '
            '$job=Join-Path $env:LOCALAPPDATA "OpenDeploy/PXVIRT-harddisk-job"; '
            '$state=Join-Path $job "state.json"; '
            'if(Test-Path -LiteralPath $state){'
            '$current=Get-Content -LiteralPath $state -Raw -Encoding UTF8 | ConvertFrom-Json; '
            'if($current.phase -eq "media_ready"){'
            'Write-Output "OpenDeploy: media already prepared. No files changed. Read docs/HANDOFF.md."; exit 0}}; '
            '& (Join-Path $root "source/pve/windows/Start-HardDisk-USB.ps1") '
            '-BundleRoot $root -PythonPath (Join-Path $root "python/python.exe")')
        # Base64 is command quoting, not a new runtime component or a credential.
        import base64
        encoded = base64.b64encode(command.encode('utf-16le')).decode('ascii')
        launcher = ('@echo off\r\nsetlocal\r\nset "OD_COMPLETE_BUNDLE=%~dp0"\r\n'
                    'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand '
                    + encoded + '\r\nexit /b %errorlevel%\r\n')
        (bundle/'START-HARDDISK-USB.cmd').write_bytes(launcher.encode('ascii'))
        (bundle/'README.txt').write_text(README, encoding='utf-8-sig')
        description = {'schema': 1, 'delivery_kind': 'complete-runtime',
                       'application_source_commit': application_commit,
                       'entrypoint': 'START-HARDDISK-USB.cmd',
                       'vm_entrypoint': 'START-VM.cmd', 'vm_platforms': ['VirtualBox'],
                       'vm_installation_verified': False,
                       'handoff': 'docs/HANDOFF.md', 'reboots_or_installs_on_start': False,
                       'installer_iso_included': False, 'credentials_included': False}
        (bundle/'bundle.json').write_text(json.dumps(description, indent=2)+'\n', encoding='utf-8')
        files = sorted(p for p in bundle.rglob('*') if p.is_file())
        staged = Path(work)/output.name
        with zipfile.ZipFile(staged, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in files:
                archive.write(path, 'OpenDeploy/'+path.relative_to(bundle).as_posix())
        metadata = description | {'base_source_commit': '725ed954c7b9eef01839c0194161179ea191d68b',
            'archive_bytes': staged.stat().st_size,
            'archive_sha256': hashlib.sha256(staged.read_bytes()).hexdigest(),
            'uncompressed_bytes': sum(p.stat().st_size for p in files), 'file_count': len(files),
            'physical_installation_performed': False}
        os.replace(staged, output)
        output.with_name('package.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--runtime-base', type=Path, required=True,
                        help='An extracted complete delivery containing python, runtime, boot-assets and assets')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--application-source-commit', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source_root, args.runtime_base, args.output, args.application_source_commit)))
