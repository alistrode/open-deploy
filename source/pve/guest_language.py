"""Prepare optional offline display-language media without Windows Update."""
import json
import pathlib
import shutil
import time
import urllib.parse
import urllib.request
import zipfile

SOURCE = 'https://api.uupdump.net/get.php?id=473c51b9-0b12-4444-86d0-75c557072b57&lang=zh-cn&edition=professional'
PACKAGES = (
    'Microsoft-Windows-Client-LanguagePack-Package_zh-cn-amd64-zh-cn.esd',
    'Microsoft-Windows-LanguageFeatures-Basic-zh-cn-Package-amd64.cab',
)


def accept_bundle(job, archive):
    cache = pathlib.Path(job)/'language-cache'/'zh-CN'
    cache.mkdir(parents=True, exist_ok=True)
    saved = {}
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) != len(PACKAGES) or {entry.filename for entry in entries} != set(PACKAGES):
                raise ValueError('中文离线包须包含指定的语言 ESD 与基础语言 CAB 两个文件')
            if any(not 0 < entry.file_size <= 96*1024**2 or
                   ((entry.external_attr >> 16) & 0o170000) == 0o120000 for entry in entries):
                raise ValueError('中文离线包的文件大小或格式无效')
            for entry in entries:
                path = cache/entry.filename
                partial = path.with_suffix(path.suffix+'.partial')
                try:
                    with bundle.open(entry) as source, partial.open('wb') as target:
                        shutil.copyfileobj(source, target, 1024*1024)
                    if partial.stat().st_size != entry.file_size:
                        raise ValueError('中文离线包上传中断')
                    partial.replace(path)
                finally:
                    partial.unlink(missing_ok=True)
                saved[entry.filename] = {'source':'offline-upload', 'size':entry.file_size}
    except zipfile.BadZipFile as error:
        raise ValueError('请选择有效的中文离线 ZIP 包') from error
    (cache/'sources.json').write_text(json.dumps(saved, indent=2)+'\n')
    return {'language':'zh-CN', 'packages':len(saved)}


def prepare(job, seed, image, language):
    language = language or image['language']
    if language == image['language']:
        return language
    if language != 'zh-CN' or image['major'] != 10 or image['build'] not in range(19041, 19046):
        raise ValueError('Offline Chinese is available for x64 Windows 10 images in the 19041 family')
    cache = pathlib.Path(job)/'language-cache'/'zh-CN'
    cache.mkdir(parents=True, exist_ok=True)
    manifest = cache/'sources.json'
    saved = json.loads(manifest.read_text()) if manifest.exists() else {}
    complete = all(name in saved and (cache/name).is_file()
                   and (cache/name).stat().st_size == saved[name]['size'] for name in PACKAGES)
    if not complete:
        try:
            with urllib.request.urlopen(SOURCE, timeout=60) as response:
                files = json.load(response)['response']['files']
        except Exception as error:
            raise ValueError('中文组件下载失败，请从页面上传离线中文包后继续') from error
        saved = {}
        for name in PACKAGES:
            item = files[name]
            url = urllib.parse.urlsplit(item['url'])
            if url.scheme not in ('http', 'https') or not url.hostname or not (
                url.hostname.endswith('.delivery.mp.microsoft.com')
                or url.hostname.endswith('.windowsupdate.com')
            ):
                raise ValueError('Language package must come from Microsoft delivery servers')
            size = int(item['size'])
            destination = cache/name
            if not destination.is_file() or destination.stat().st_size != size:
                partial = destination.with_suffix(destination.suffix+'.partial')
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(item['url'], timeout=120) as source, partial.open('wb') as target:
                            shutil.copyfileobj(source, target, 1024*1024)
                        if partial.stat().st_size != size:
                            raise ValueError('Language package download was interrupted')
                        partial.replace(destination)
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        time.sleep(2*(attempt+1))
            saved[name] = {'source': item['url'], 'size': size}
        manifest.write_text(json.dumps(saved, indent=2)+'\n')
    target = pathlib.Path(seed)/'OpenDeploy'/'Language'/'zh-CN'
    target.mkdir(parents=True, exist_ok=True)
    for name in PACKAGES:
        shutil.copy2(cache/name, target/name)
    return language
