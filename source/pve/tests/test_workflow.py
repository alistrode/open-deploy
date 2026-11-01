import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('opendeploy_pve',ROOT/'opendeploy.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)


def plan():
    return {'schema':1,'id':str(uuid.uuid4()),'relay_version':'3.0','host':{'disk_serial':'TEST-SERIAL','fqdn':'opendeploy.home.arpa'},
            'vm':{'vmid':110,'name':'tiny10','storage':'local-lvm','iso_storage':'local','bridge':'vmbr0','cores':4,'memory_mb':8192,'disk_gb':100,'uuid':str(uuid.uuid4()),'image_index':1},
            'assets':{'pxvirt':{'path':'px.iso','sha256':m.PX_ISO_SHA},'relay':{'path':'relay.tar.gz','sha256':m.RELAY_SHA},'virtio':{'path':'virtio.iso','sha256':m.VIRTIO_SHA}},
            'windows_user':'operator','windows_password':'Private<&Password','host_password':'PrivateTestOnly'}


class FakeHost:
    def __init__(self,p):
        self.p=p;self.v=p['vm'];self.vmid=str(self.v['vmid']);self.c=None;self.running=False;self.snap=False;self.calls=[];self.crash_create=False;self.fail_health=False;self.fail_snapshot=False;self.crash_start=False
    def bind(self,j):pass
    def config(self):return self.c
    def owned(self):
        if not self.c or self.c.get('description')!='OpenDeploy-'+self.p['id']:raise ValueError('not owned')
        return self.c
    def volume(self,key):return 'local:iso/'+key+'.iso'
    def qm(self,*args,**kwargs):
        self.calls.append(args)
        if args[0]=='create':
            self.c={'description':'OpenDeploy-'+self.p['id'],'smbios1':'uuid='+self.v['uuid'],'cores':str(self.v['cores']),'memory':str(self.v['memory_mb']),'ostype':'win10','bios':'seabios','sata0':'owned-disk','ide0':'virtio','ide1':'seed','ide2':'windows'}
            if self.crash_create:self.crash_create=False;raise subprocess.TimeoutExpired('qm',1)
        elif args[0]=='start':
            self.running=True
            if self.crash_start:self.crash_start=False;raise subprocess.TimeoutExpired('qm',1)
        elif args[0] in ['stop','shutdown']:self.running=False
        elif args[0]=='snapshot':
            if self.fail_snapshot:raise RuntimeError('storage backend rejected snapshot')
            self.snap=True
        return subprocess.CompletedProcess(args,0,'','')
    def status(self):return 'running' if self.running else 'stopped'
    def wait_guest(self,seconds):
        if not self.running or self.fail_health:raise ValueError('guest not healthy')
        return {'healthy':True}
    def stable(self):return self.snap
    def rdp(self):pass
    def snapshots(self):return [{'name':'od-stable','description':'OpenDeploy-'+self.p['id']}] if self.snap else []


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.job=pathlib.Path(self.tmp.name);self.p=plan();self.j=m.Journal(self.job/'state.json',self.p);self.h=FakeHost(self.p)
        self.mock=patch.object(m,'Host',return_value=self.h);self.mock.start()
    def tearDown(self):self.mock.stop();self.tmp.cleanup()
    def host_ready(self):
        self.j.advance('media.done',{'inputs_verified','boot_preserved'});self.j.advance('host.done',{'host_bound','relay_running'})
    def install(self):self.host_ready();m.install(self.job,self.p,self.j)
    def test_no_success_before_healthy_guest(self):
        self.install();self.h.fail_health=True
        with self.assertRaises(ValueError):m.finalize(self.job,self.p,self.j,0)
        self.assertEqual(self.j.data['phase'],'installing');self.assertFalse(self.h.snap)
    def test_foreign_vm_is_never_modified(self):
        self.host_ready();self.h.c={'description':'someone-else'}
        with self.assertRaises(ValueError):m.install(self.job,self.p,self.j)
        self.assertEqual(self.h.calls,[])
    def test_create_timeout_adopts_same_owned_vm_without_duplicate_disk(self):
        self.host_ready();self.h.crash_create=True
        with self.assertRaises(subprocess.TimeoutExpired):m.install(self.job,self.p,self.j)
        self.assertEqual(self.j.data['phase'],'vm_creating')
        m.install(self.job,self.p,self.j)
        self.assertEqual(sum(c[0]=='create' for c in self.h.calls),1)
        self.assertEqual(self.j.data['phase'],'installing')
    def test_repeated_install_does_not_replay_installation(self):
        self.install();before=list(self.h.calls);m.install(self.job,self.p,self.j)
        self.assertEqual(self.h.calls,before)
    def test_snapshot_failure_not_complete(self):
        self.install();self.h.fail_snapshot=True
        with self.assertRaises(RuntimeError):m.finalize(self.job,self.p,self.j,0)
        self.assertEqual(self.j.data['phase'],'snapshotting')
        self.h.fail_snapshot=False;m.finalize(self.job,self.p,self.j,0)
        self.assertEqual(self.j.data['phase'],'complete')
    def test_resume_snapshotting_when_guest_stopped(self):
        self.install();self.j.advance('guest.done',{'vm_owned','guest_bound','guest_healthy'});self.j.advance('snapshot.intent',{'vm_owned','guest_bound','guest_healthy'})
        self.h.running=False;m.finalize(self.job,self.p,self.j,0)
        self.assertEqual(self.j.data['phase'],'complete')
    def test_start_timeout_after_snapshot_does_not_replace_stable(self):
        self.install();self.h.crash_start=True
        with self.assertRaises(subprocess.TimeoutExpired):m.finalize(self.job,self.p,self.j,0)
        m.finalize(self.job,self.p,self.j,0)
        self.assertEqual(sum(c[0]=='snapshot' for c in self.h.calls),1)
    def test_recovery_preserves_original_stable_snapshot(self):
        self.install();m.finalize(self.job,self.p,self.j,0);m.restore(self.job,self.p,self.j,0)
        self.assertEqual(sum(c[0]=='snapshot' for c in self.h.calls),1)
        self.assertEqual(sum(c[0]=='rollback' for c in self.h.calls),1)
        self.assertEqual(self.j.data['phase'],'complete')
    def test_plan_change_rejected_after_restart(self):
        self.host_ready();self.p['vm']['vmid']=111
        with self.assertRaises(ValueError):m.Journal(self.j.path,self.p)
    def test_formal_snapshot_fact_required_by_runtime(self):
        self.install();self.j.advance('guest.done',{'vm_owned','guest_bound','guest_healthy'});self.j.advance('snapshot.intent',{'vm_owned','guest_bound','guest_healthy'})
        with self.assertRaises(ValueError):self.j.advance('snapshot.done',{'vm_owned','guest_bound','guest_healthy'})
    def test_exact_physical_disk_filter_and_no_wildcards(self):
        import tomllib
        answer=m.host_answer(self.p);d=tomllib.loads(answer);self.assertEqual(d['disk-setup']['filter']['ID_SERIAL_SHORT'],'TEST-SERIAL')
        self.assertTrue(d['global']['root_password_hashed'].startswith('$6$'))
        self.assertNotIn(self.p['host_password'],answer)
        m.atomic(self.job/'plan.json',self.p);self.assertEqual(m.load(self.job/'plan.json')['relay_version'],'3.0')
        self.p['host']['disk_serial']='*';m.atomic(self.job/'plan.json',self.p)
        with self.assertRaises(ValueError):m.load(self.job/'plan.json')
    def test_host_password_hash_never_uses_platform_text_newlines(self):
        with patch.object(m.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, b'$6$test$hash\n', b'')
            m.host_answer(self.p)
            options = run.call_args.kwargs
            self.assertEqual(options['input'], (self.p['host_password']+'\n').encode('utf-8'))
            self.assertFalse(options.get('text', False))
            self.assertNotIn(b'\r', options['input'])
    def test_supervised_pipeline_recovers_three_snapshot_failures(self):
        import re
        unit=(ROOT/'templates/opendeploy-stage2.service').read_text()
        commands=re.findall(r'^ExecStart=.*?opendeploy\.py (\w+) ',unit,re.M)
        self.assertEqual(commands,['bootstrap','install','finalize'])
        self.assertIn('TimeoutStartSec=infinity',unit)
        self.assertIn('Restart=on-failure',unit)
        self.host_ready()
        original=self.h.qm
        remaining=[3]
        def flaky(*args,**kwargs):
            if args[0]=='snapshot' and remaining[0]:
                remaining[0]-=1
                raise RuntimeError('transient storage failure')
            return original(*args,**kwargs)
        self.h.qm=flaky
        for attempt in range(4):
            self.j=m.Journal(self.j.path,self.p)
            try:
                for command in commands:
                    if command=='bootstrap':continue  # Host identity/relay already ready.
                    if command=='install':m.install(self.job,self.p,self.j)
                    else:m.finalize(self.job,self.p,self.j,0)
            except RuntimeError:
                self.assertEqual(self.j.data['phase'],'snapshotting')
                continue
        self.assertEqual(self.j.data['phase'],'complete')
        self.assertEqual(sum(c[0]=='create' for c in self.h.calls),1)
        self.assertEqual(sum(c[0]=='snapshot' for c in self.h.calls),1)
        self.assertTrue(self.h.running)

    def test_version_four_is_rejected(self):
        self.p['relay_version']='4.0';m.atomic(self.job/'plan.json',self.p)
        with self.assertRaises(ValueError):m.load(self.job/'plan.json')
    def test_unattended_xml_has_escaped_password_and_explicit_virtual_disk(self):
        from xml.etree import ElementTree as E
        s=m.unattended(self.p);root=E.fromstring(s);ns={'u':'urn:schemas-microsoft-com:unattend'}
        self.assertIn('Private&lt;&amp;Password',s)
        self.assertEqual(root.find('.//u:DiskID',ns).text,'0')
        self.assertEqual(root.find('.//u:Password/u:Value',ns).text,self.p['windows_password'])
    def test_community_boot_parameter_matches_installer(self):
        text='linux /boot/linux26 Pxvirt-start-auto-installer\n'*2
        patched=m.patch_boot_menu(text)
        self.assertEqual(patched.count('proxmox-start-auto-installer'),2)
        self.assertNotIn('Pxvirt-start-auto-installer',patched)
        with self.assertRaises(ValueError):m.patch_boot_menu('unknown menu')

    def test_image_metadata_drives_language_and_rejects_wrong_index(self):
        import types
        def extract(args, **kwargs):
            pathlib.Path(args[-1]).write_bytes(b'fixture')
            return types.SimpleNamespace(returncode=0)
        metadata=b'<WIM><IMAGE INDEX="1"><WINDOWS><ARCH>9</ARCH><LANGUAGES><DEFAULT>zh-CN</DEFAULT></LANGUAGES></WINDOWS></IMAGE></WIM>'
        with patch.object(m,'call',side_effect=extract), patch.object(m.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=metadata)):
            self.assertEqual(m.windows_language('fixture.iso',1),'zh-CN')
            with self.assertRaises(ValueError):m.windows_language('fixture.iso',2)

    def test_concurrent_worker_is_rejected(self):
        with m.locked(self.job/'state.json'):
            with self.assertRaises(BlockingIOError):
                with m.locked(self.job/'state.json'):pass


if __name__=='__main__':unittest.main()
