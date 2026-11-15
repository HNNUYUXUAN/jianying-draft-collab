import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import native_runtime as r
import native_bridge as n
from native_probe import probe


class DeviceNativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patches=[patch.object(r,'ROOT',self.root),patch.dict(os.environ,{'JY_NATIVE_STATE_DIR':str(self.root/'state')})]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def app(self,name):
        folder=self.root/name;folder.mkdir()
        for filename in r.CORE_FILES:(folder/filename).write_bytes((name+filename).encode())
        return folder

    def accepted(self,app,capabilities=None,descriptor=None):
        identity=r.inventory(app);descriptor=descriptor or r.descriptor_for(identity)
        receipt={'status':'ready','protocol':r.PROTOCOL,'identity':identity,'adapter':descriptor,
                 'adapter_sha256':r.adapter_hash(descriptor),'capabilities':capabilities or {'read':'passed','create':'passed'},'evidence':'fixture'}
        r.write(r.state_root()/identity['fingerprint']/'receipt.json',receipt)
        return identity,receipt

    def test_unknown_version_can_be_verified_without_shipped_whitelist(self):
        app=self.app('99.1.2.3');self.accepted(app)
        self.assertEqual(r.doctor_report(app)['status'],'ready')
        self.assertIsNone(r.doctor_report(app)['known_profile'])

    def test_tool_change_revokes_receipt(self):
        app=self.app('11.7.0.14652');self.accepted(app)
        (app/'lyra-cli.exe').write_bytes(b'new executable revision')
        self.assertEqual(r.doctor_report(app)['status'],'needs_probe')
        with self.assertRaises(r.NativePreflightError):r.require(app,'read')

    def test_capabilities_are_granted_separately(self):
        app=self.app('99.0');self.accepted(app,{'read':'passed'})
        self.assertEqual(r.doctor_report(app,['read'])['status'],'ready')
        self.assertNotEqual(r.doctor_report(app,['audio_volume'])['status'],'ready')
        with self.assertRaises(r.NativePreflightError):r.require(app,'create')

    def test_false_receipt_status_is_not_accepted(self):
        app=self.app('99.0');identity,receipt=self.accepted(app)
        receipt['status']='needs_local_adapter'
        r.write(r.state_root()/identity['fingerprint']/'receipt.json',receipt)
        self.assertIsNone(r.receipt_for(identity))

    def test_remembered_usable_installation_wins_over_newer_folder(self):
        older=self.app('11.7.0.14652');newer=self.app('99.0.0.1');self.accepted(older)
        r.write(r.state_root()/'selection.json',{'app':str(older)})
        with patch.object(r,'running_apps',return_value=[newer]),patch.object(r,'discover',return_value=[older,newer]):
            chosen,reason=r.resolve_app()
        self.assertEqual(chosen,older.resolve());self.assertEqual(reason,'remembered')

    def test_explicit_selection_wins_over_remembered(self):
        older=self.app('11.7.0.14652');newer=self.app('99.0.0.1')
        r.write(r.state_root()/'selection.json',{'app':str(older)})
        self.assertEqual(r.resolve_app(newer)[0],newer.resolve())

    def test_configured_relative_paths_resolve_from_runtime(self):
        app=self.app('installed-app')
        r.write(self.root/'runtime-config.json',{'jianying':{'app':'installed-app','projects':'drafts'}})
        self.assertEqual(r.resolve_app()[0],app.resolve())
        self.assertEqual(r.projects_root(),(self.root/'drafts').resolve())

    def test_multiple_unknown_installations_need_selection(self):
        a=self.app('11.0');b=self.app('99.0')
        with patch.object(r,'running_apps',return_value=[]),patch.object(r,'discover',return_value=[a,b]):
            with self.assertRaisesRegex(r.NativePreflightError,'Several'):r.resolve_app()

    def test_local_adapter_module_change_revokes_receipt(self):
        app=self.app('99.0');folder=r.state_root()/'local/test';folder.mkdir(parents=True)
        module=folder/'adapter.py';module.write_text('def execute(*args,**kwargs): return {}')
        desc=folder/'adapter.json';r.write(desc,{'id':'local-test','kind':'local_python','module':'adapter.py'})
        descriptor=r.descriptor_for(r.inventory(app),desc);identity,_=self.accepted(app,descriptor=descriptor)
        module.write_text('def execute(*args,**kwargs): return {"changed":True}')
        self.assertIsNone(r.receipt_for(identity))

    def test_project_supplied_adapter_is_not_executable_configuration(self):
        app=self.app('99.0');desc=self.root/'untrusted.json';r.write(desc,{'kind':'local_python','module':'evil.py'})
        with self.assertRaisesRegex(r.NativePreflightError,'authored and reviewed'):r.descriptor_for(r.inventory(app),desc)

    def test_unverified_production_call_never_launches_native_process(self):
        app=self.app('99.0')
        with patch.object(n.subprocess,'run')as launch,self.assertRaises(r.NativePreflightError):
            n.run(app,['draft','extract','--ref','local:///fixture'])
        launch.assert_not_called()

    def test_failed_probe_does_not_promote_partial_capabilities(self):
        app=self.app('99.0');projects=self.root/'projects';projects.mkdir()
        index=projects/'root_meta_info.json';index.write_text('{"user":"unchanged"}')
        before=index.read_bytes()
        def fake_transport(app,args,*unused,**kwargs):
            if '--help'in args:return subprocess.CompletedProcess([],0,b'--ref --dir --resource',b'')
            raise ValueError('fixture: no supported create protocol')
        with patch.object(r,'projects_root',return_value=projects),patch.object(n,'transport',side_effect=fake_transport):
            report=probe(self.root/'probe',app)
        self.assertEqual(report['status'],'needs_local_adapter')
        self.assertEqual(index.read_bytes(),before)
        self.assertFalse(list(r.state_root().glob('*/receipt.json')))

    def test_unknown_actions_cannot_borrow_read_permission(self):
        with self.assertRaises(r.NativePreflightError):r.capability_for(['draft','project','focus'])


if __name__=='__main__':unittest.main(verbosity=2)
