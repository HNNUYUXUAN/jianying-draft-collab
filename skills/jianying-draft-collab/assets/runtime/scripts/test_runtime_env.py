import tempfile,unittest
from contextlib import ExitStack
from types import SimpleNamespace
import sys
from pathlib import Path
from unittest.mock import patch
import runtime_env as env

class RuntimeTests(unittest.TestCase):
    def fake_checks(self,root):
        stack=ExitStack();stack.enter_context(patch.object(env,'ROOT',root))
        for name in ['_core','_media','_font']:
            stack.enter_context(patch.object(env,name,return_value={'fingerprint':name+'-pin'}))
        for name in ['_music','_native']:
            stack.enter_context(patch.object(env,name,return_value={'status':'passed','detail':{'fixture':name},'fingerprint':name+'-pin'}))
        stack.enter_context(patch.object(env,'_cloud',return_value={'status':'missing_configuration','detail':{'configured':False},'reason':'fixture has no key'}))
        return stack

    def save_smoke(self,root,name,capabilities,fingerprints):
        artifact=root/(name+'.bin');artifact.write_bytes(name.encode())
        env.write(root/'state'/('smoke-'+name+'.json'),{'capabilities':capabilities,'fingerprints':fingerprints,
            'report':name,'artifacts':[{'path':str(artifact),'sha256':env.digest(artifact)}]})
        return artifact

    def test_local_recheck_preserves_current_full_smoke_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.fake_checks(root):
                full=env.doctor(require_smoke=False)
                self.save_smoke(root,'full',env.TASKS['local'],full['fingerprints'])
                local=env.doctor(task='install',require_smoke=False)
                self.save_smoke(root,'local',env.TASKS['install'],local['fingerprints'])
                env.write(root/'state/smoke-latest.json',env.read(root/'state/smoke-local.json'))
                before={p.relative_to(root):env.digest(p)for p in root.rglob('*')if p.is_file()}
                result=env.doctor()
                self.assertTrue(result['ready'])
                self.assertTrue(result['smoke']['receipt'].endswith('smoke-full.json'))
                self.assertEqual(before,{p.relative_to(root):env.digest(p)for p in root.rglob('*')if p.is_file()})

    def test_local_only_receipt_never_grants_native(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.fake_checks(root):
                local=env.doctor(task='install',require_smoke=False)
                self.save_smoke(root,'local',env.TASKS['install'],local['fingerprints'])
                self.assertTrue(env.doctor(task='music')['ready'])
                self.assertFalse(env.doctor()['ready'])
                self.assertIn('smoke_cache',env.doctor()['failed'])

    def test_corrupt_full_artifact_does_not_revoke_valid_local_music(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.fake_checks(root):
                full=env.doctor(require_smoke=False)
                artifact=self.save_smoke(root,'full',env.TASKS['local'],full['fingerprints'])
                self.save_smoke(root,'local',env.TASKS['install'],full['fingerprints'])
                artifact.write_bytes(b'changed')
                self.assertFalse(env.doctor()['ready'])
                self.assertTrue(env.doctor(task='music')['ready'])

    def test_dependency_fingerprint_change_requires_new_smoke(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.fake_checks(root):
                current=env.doctor(task='music',require_smoke=False)
                self.save_smoke(root,'local',env.TASKS['install'],current['fingerprints'])
                with patch.object(env,'_music',return_value={'status':'passed','detail':{},'fingerprint':'updated-renderer'}):
                    self.assertFalse(env.doctor(task='music')['ready'])

    def test_closeout_requests_only_native_read_and_no_music_or_cloud_key(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.fake_checks(root):
                full=env.doctor(require_smoke=False)
                self.save_smoke(root,'full',env.TASKS['local'],full['fingerprints'])
                with patch.object(env,'_native',return_value={'status':'passed','detail':{},'fingerprint':'_native-pin'})as native,patch.object(env,'_music')as music:
                    result=env.preflight(task='closeout')
                    self.assertTrue(result['ready'])
                    native.assert_called_once_with(['read'])
                    music.assert_not_called()
                    self.assertEqual(result['required'],['core','media','native'])

    def test_closeout_without_render_smoke_uses_current_read_probe(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.fake_checks(root):
                result=env.doctor(task='closeout')
                self.assertTrue(result['ready'])
                self.assertEqual(result['smoke']['status'],'not_required')
                self.assertEqual(result['smoke']['scope'],'closeout_read_and_media_checks')
                self.assertFalse((root/'state').exists())
                with patch.object(env,'_native',return_value={'status':'failed','reason':'current read probe is no longer valid','detail':{}}):
                    failed=env.preflight(task='closeout')
                    self.assertFalse(failed['ready'])
                    self.assertIn('native',failed['failed'])

    def test_first_install_tools_ready_without_preexisting_smoke(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.fake_checks(root):
                result=env.doctor(task='install',full=True)
                self.assertTrue(result['ready'])
                self.assertEqual(result['smoke']['scope'],'installation_tool_checks')
                self.assertFalse(result['api_called'])
                self.assertFalse((root/'state').exists())
                self.assertFalse(env.preflight(task='music')['ready'])

    def test_music_algorithm_hash_invalidates_music_without_changing_native(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'scripts').mkdir()
            code=root/'scripts/music_v2.py';code.write_text('first',encoding='utf-8')
            fake_music=SimpleNamespace(doctor=lambda *a,**kw:{'status':'passed','fingerprint':'engine-pin'})
            fake_native=SimpleNamespace(doctor_report=lambda **kw:{'status':'ready','identity':{'app':'fixture'}})
            with patch.object(env,'ROOT',root),patch.dict(sys.modules,{'music_adapter':fake_music,'native_runtime':fake_native}):
                before_music=env._music(None)['fingerprint'];before_native=env._native()['fingerprint']
                code.write_text('second',encoding='utf-8')
                self.assertNotEqual(before_music,env._music(None)['fingerprint'])
                self.assertEqual(before_native,env._native()['fingerprint'])

    def test_incomplete_environment_stops_before_paid_synthesis(self):
        import video
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            env.write(root/'sources.json',[])
            env.write(root/'production-plan.json',{'version':1,'fps':60,'music':{'mode':'none'},'segments':[{'id':'N01','frames':5400,'text':'测试','image_id':'P01'}]})
            with patch.object(env,'preflight',return_value={'ready':False,'failed':['scipy']}),patch.object(video,'assemble') as paid:
                with self.assertRaisesRegex(RuntimeError,'scipy'):video.build(root)
                paid.assert_not_called()

    def test_provision_requires_pinned_bytes_and_keeps_existing(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'source';(src/'bin').mkdir(parents=True)
            for name in ('ffmpeg.exe','ffprobe.exe'):(src/'bin'/name).write_bytes(name.encode())
            for name in ('LICENSE','README.txt'):(src/name).write_text('license')
            env.write(root/'media-toolchain.json',{'version':'fixture','files':{n:env.digest(src/'bin'/n) for n in ('ffmpeg.exe','ffprobe.exe')}})
            with patch.object(env,'ROOT',root):
                self.assertEqual(env.provision_media(src)['status'],'installed')
                self.assertEqual(env.provision_media(src)['status'],'reused')
                target=root/'tools/ffmpeg/bin/ffmpeg.exe';target.write_bytes(b'changed')
                with self.assertRaises(RuntimeError):env.provision_media(src)
                self.assertEqual(target.read_bytes(),b'changed')

    def test_rejects_missing_binary_before_install(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);env.write(root/'media-toolchain.json',{'version':'fixture','files':{'ffmpeg.exe':'bad'}})
            with patch.object(env,'ROOT',root):
                with self.assertRaises(RuntimeError):env.provision_media(root/'absent')
            self.assertFalse((root/'tools/ffmpeg').exists())

if __name__=='__main__':unittest.main()
