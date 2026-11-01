"""Post-install product entry for selecting or uploading guest installation media."""
import hmac
import json
import pathlib
import re
import secrets
import ssl
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import opendeploy as od

JOB = pathlib.Path('/opt/opendeploy')
PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>OpenDeploy</title><style>body{font:17px system-ui;max-width:740px;margin:50px auto;padding:20px;background:#f5f7fa;color:#172033}section{background:white;padding:28px;border-radius:18px}label{display:block;margin:20px 0}input,select,button{font:inherit;padding:9px;max-width:100%;box-sizing:border-box}select{width:100%}button{cursor:pointer}#message{white-space:pre-wrap}</style>
<section><h1>PXVIRT 已就绪</h1><p>模拟流程可在这里结束。需要继续安装 Tiny10 时，再选择镜像。</p>
<p id="status"></p><label>Tiny10 镜像<select id="windows"></select></label>
<label>VirtIO 驱动介质<select id="virtio"></select></label>
<label>Windows 镜像索引 <input id="index" type="number" min="1" value="1"></label>
<details><summary>上传本地 ISO</summary><label>保存位置<select id="storage"></select></label><input id="file" type="file" accept=".iso"><button id="upload">上传</button><p>已有共享存储中的镜像可直接从上方列表选择。也可在下方接入新的 NFS 共享。</p></details>
<details><summary>接入 NFS 共享存储</summary><label>存储名称 <input id="shareName" placeholder="tiny10-media"></label><label>服务器 <input id="shareServer" placeholder="192.168.1.10"></label><label>共享目录 <input id="shareExport" placeholder="/images"></label><button id="share">接入共享</button></details>
<p><button id="start">安装 Tiny10 / 从中断处继续</button></p><p id="message" role="status"></p></section>
<script>
const token=location.hash.slice(1);history.replaceState(null,'',location.pathname);
const el=id=>document.getElementById(id);let phase='';
async function api(path,options={}){options.headers={...options.headers,Authorization:'Bearer '+token};const r=await fetch(path,options);const v=await r.json();if(!r.ok)throw Error(v.error||'操作失败');return v;}
function message(s){el('message').textContent=s;}
async function refresh(){const s=await api('/status');phase=s.phase;el('status').textContent='当前阶段：'+s.label;el('start').disabled=!['host_ready','vm_creating','installing','guest_ready','snapshotting','complete'].includes(phase);}
async function media(){const m=await api('/media');for(const key of ['windows','virtio']){const select=el(key),previous=select.value;select.replaceChildren();for(const v of m.volumes){const o=document.createElement('option');o.value=v;o.textContent=v;select.append(o);}if(m.volumes.includes(previous))select.value=previous;}el('storage').replaceChildren();for(const v of m.storages){const o=document.createElement('option');o.value=v;o.textContent=v;el('storage').append(o);}if(m.selection){el('windows').value=m.selection.assets.windows.volume;el('virtio').value=m.selection.assets.virtio.volume;el('index').value=m.selection.vm.image_index;}}
el('upload').onclick=async()=>{el('upload').disabled=true;try{const f=el('file').files[0];if(!f)throw Error('请选择 ISO');message('正在上传，请保持页面打开…');const v=await api('/upload?storage='+encodeURIComponent(el('storage').value),{method:'PUT',body:f});await media();el(f.name.toLowerCase().includes('virtio')?'virtio':'windows').value=v.volume;message('上传完成：'+v.volume);}catch(e){message(e.message);}finally{el('upload').disabled=false;}};
el('share').onclick=async()=>{el('share').disabled=true;try{await api('/storage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:el('shareName').value,server:el('shareServer').value,export:el('shareExport').value})});await media();message('共享存储已接入，可从列表选择 ISO。');}catch(e){message(e.message);}finally{el('share').disabled=false;}};
el('start').onclick=async()=>{el('start').disabled=true;try{const v=await api('/continue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({windows:el('windows').value,virtio:el('virtio').value,image_index:Number(el('index').value)})});message(v.message);await refresh();}catch(e){message(e.message);el('start').disabled=false;}};
(async()=>{try{await refresh();await media();}catch(e){message(e.message);}})();
</script></html>'''


def media():
    status = json.loads(od.call(['pvesm','status','--content','iso','--output-format','json']).stdout)
    storages = [s['storage'] for s in status if s.get('active')]
    volumes = []
    for storage in storages:
        listing = json.loads(od.call(['pvesm','list',storage,'--content','iso','--output-format','json']).stdout)
        volumes.extend(v['volid'] for v in listing if v['volid'].lower().endswith('.iso'))
    selection = JOB/'guest-selection.json'
    saved = json.loads(selection.read_text()) if selection.exists() else None
    return {'storages':storages, 'volumes':volumes, 'selection':saved}


class Handler(BaseHTTPRequestHandler):
    # Access tokens and user-selected paths must never enter HTTP access logs.
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(180)

    def reply(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        expected = 'Bearer '+self.server.token
        if not hmac.compare_digest(self.headers.get('Authorization','').encode(), expected.encode()):
            self.reply({'error':'请使用准备电脑上的“继续部署”入口打开此页面。'},401)
            return False
        return True

    def do_GET(self):
        if self.path == '/':
            data = PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Frame-Options','DENY')
            self.end_headers()
            self.wfile.write(data)
            return
        if not self.authorized(): return
        try:
            if self.path == '/media': return self.reply(media())
            if self.path == '/status':
                state = json.loads((JOB/'state.json').read_text())
                phase = state['phase']
                labels = {'media_ready':'正在配置 PXVIRT','host_ready':'PXVIRT 就绪，等待选择镜像',
                          'vm_creating':'正在创建虚拟机','installing':'正在安装 Windows',
                          'guest_ready':'正在配置远程连接','complete':'部署完成'}
                return self.reply({'phase':phase,'label':labels.get(phase,phase)})
            self.reply({'error':'页面不存在'},404)
        except Exception:
            self.reply({'error':'无法读取当前任务，请在 PXVIRT 上查看部署日志。'},500)

    def do_PUT(self):
        if not self.authorized(): return
        destination = None
        try:
            url = urllib.parse.urlsplit(self.path)
            if url.path != '/upload': return self.reply({'error':'页面不存在'},404)
            storage = urllib.parse.parse_qs(url.query).get('storage',[''])[0]
            if storage not in media()['storages']: raise ValueError('请选择已有 ISO 存储')
            length = int(self.headers.get('Content-Length','0'))
            if length <= 0 or length > 64*1024**3: raise ValueError('请选择不超过 64 GiB 的 ISO')
            volume = storage+':iso/od-upload-'+secrets.token_hex(16)+'.iso'
            destination = pathlib.Path(od.call(['pvesm','path',volume]).stdout.strip())
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_suffix('.iso.partial')
            try:
                with partial.open('xb') as stream:
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(1024*1024,remaining))
                        if not chunk: raise ValueError('上传中断，请重新上传该文件')
                        stream.write(chunk)
                        remaining -= len(chunk)
                partial.replace(destination)
            finally:
                partial.unlink(missing_ok=True)
            self.reply({'volume':volume})
        except ValueError as error:
            self.reply({'error':str(error)},400)
        except Exception:
            self.reply({'error':'上传失败，请确认所选存储可写且空间足够。'},500)

    def do_POST(self):
        if not self.authorized(): return
        if self.path not in ('/continue','/storage'): return self.reply({'error':'页面不存在'},404)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 8192: raise ValueError('配置无效')
            selected = json.loads(self.rfile.read(length))
            if self.path == '/storage':
                name = selected.get('name','').strip()
                server = selected.get('server','').strip()
                export = selected.get('export','').strip()
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,62}',name):
                    raise ValueError('请输入字母开头的存储名称')
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}',server):
                    raise ValueError('请输入共享服务器地址')
                if not export.startswith('/') or any(c in export for c in '\r\n\x00'):
                    raise ValueError('请输入绝对共享目录')
                od.call(['pvesm','add','nfs',name,'--server',server,'--export',export,'--content','iso'],timeout=180)
                return self.reply({'message':'共享存储已接入'})
            plan = od.load(JOB/'plan.json')
            with od.locked(JOB/'state.json'):
                journal = od.Journal(JOB/'state.json',plan)
                if journal.data['phase'] == 'complete':
                    return self.reply({'message':'部署已完成，不重复安装。'})
                if journal.data['phase'] == 'host_ready':
                    receipt = JOB/'guest-selection.json'
                    if receipt.exists():
                        prior = json.loads(receipt.read_text())
                        if (prior['assets']['windows']['volume'] != selected['windows']
                                or prior['assets']['virtio']['volume'] != selected['virtio']
                                or prior['vm']['image_index'] != selected['image_index']):
                            raise ValueError('镜像选择已保存，请继续现有任务，不要替换已提交的镜像')
                    else:
                        od.select_guest_media(JOB,plan,journal,selected['windows'],selected['virtio'],selected['image_index'])
            od.call(['systemctl','enable','--now','--no-block','opendeploy-guest.service'])
            self.reply({'message':'已开始或继续安装；发生错误时保留当前进度，日志由 PXVIRT 部署服务记录。'})
        except (ValueError,KeyError) as error:
            self.reply({'error':str(error)},400)
        except Exception:
            self.reply({'error':'继续部署失败，当前进度已保留，请查看 PXVIRT 部署日志。'},500)


def main():
    access = json.loads((JOB/'portal-access.json').read_text())
    server = ThreadingHTTPServer(('0.0.0.0',access['port']),Handler)
    server.daemon_threads = True
    server.token = access['token']
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain('/etc/pve/local/pve-ssl.pem','/etc/pve/local/pve-ssl.key')
    server.socket = context.wrap_socket(server.socket,server_side=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
