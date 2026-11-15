import copy,json,subprocess,sys,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from pipeline import sha,write
from visual_assets import audit_images
from video import build,validate

class VisualAssetTests(unittest.TestCase):
    def fixture(self, root):
        (root/'engineering').mkdir()
        Image.new('RGB',(16,9),'white').save(root/'original.png')
        (root/'prompt.txt').write_text('创建图片：完整文字和实测数据',encoding='utf-8')
        image={'path':'original.png','sha256':sha(root/'original.png'),'qa':{'facts':'passed','text':'passed','visual':'passed'}}
        plan={'version':1,'fps':60,'visual_asset_manifest':'engineering/visual-assets.json','images':{'card':image},
              'segments':[{'id':'intro','frames':5400,'text':'测量平均速度。','image_id':'card'}]}
        manifest={'version':1,'source_reviews':{},'assets':[{'image_id':'card','lane':'web_chatgpt_chrome','mode':'create_image',
            'conversation_url':'https://chatgpt.com/c/fixture-completed','prompt':{'path':'prompt.txt','sha256':sha(root/'prompt.txt')},
            'original':{'path':'original.png','sha256':sha(root/'original.png')},'qa':image['qa'],
            'usage':[{'segment_id':'intro','type':'image'}]}]}
        return plan,manifest,{}
    def save(self,root,plan,manifest,sources):
        write(root/'production-plan.json',plan);write(root/'engineering/visual-assets.json',manifest);write(root/'sources.json',list(sources.values()))
    def test_complete_generated_asset_audit_is_read_only_and_cli_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p);self.save(p,plan,m,s)
            before={str(f.relative_to(p)):sha(f) for f in p.rglob('*') if f.is_file()}
            self.assertEqual(audit_images(p)['generated_assets'],1)
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('video.py')),'audit-images','--project',str(p)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'],'passed')
            self.assertEqual(before,{str(f.relative_to(p)):sha(f) for f in p.rglob('*') if f.is_file()})
    def test_generated_text_data_and_chart_pages_have_one_required_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p)
            for kind in ['文字卡','流程卡','数据表','计算图','曲线图','原理图','封面']:
                (p/'prompt.txt').write_text('创建'+kind,encoding='utf-8');m['assets'][0]['prompt']['sha256']=sha(p/'prompt.txt')
                for lane in ['programmatic','native_imagegen','pillow']:
                    m['assets'][0]['lane']=lane;self.save(p,plan,m,s)
                    with self.assertRaisesRegex(ValueError,'Chrome ChatGPT'):audit_images(p)
            m['assets'][0]['lane']='web_chatgpt_chrome';m['assets'][0]['mode']='chat'
            self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'Chrome ChatGPT'):audit_images(p)
    def test_prompt_original_and_conversation_provenance_are_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p)
            changes=[('prompt',{'path':'missing.txt','sha256':'0'*64}),('original',{'path':'original.png','sha256':'0'*64}),
                     ('conversation_url','https://example.com/c/fixture'),('conversation_url','https://chatgpt.com/c/local-chatgpt%3Afixture'),
                     ('qa',{'facts':'passed','text':'pending','visual':'passed'})]
            for key,value in changes:
                bad=copy.deepcopy(m);bad['assets'][0][key]=value;self.save(p,plan,bad,s)
                with self.assertRaises(ValueError):audit_images(p)
            bad=copy.deepcopy(m);bad['assets'][0]['prompt']['path']='../prompt.txt';self.save(p,plan,bad,s)
            with self.assertRaisesRegex(ValueError,'leaves project'):audit_images(p)
    def test_programmatic_replacement_after_generation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p)
            Image.new('RGB',(16,9),'red').save(p/'redrawn.png')
            plan['images']['card'].update(path='redrawn.png',sha256=sha(p/'redrawn.png'))
            self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'downloaded original'):audit_images(p)
    def test_derived_static_pages_cannot_be_omitted_from_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p);(p/'composite.mp4').write_bytes(b'unit test source bytes')
            s['D1']={'id':'D1','path':str(p/'composite.mp4'),'duration_us':10000000,'sha256':sha(p/'composite.mp4')}
            plan['segments'].append({'id':'operation','frames':600,'source_id':'D1','text':'操作演示。'})
            interval={'image_id':'card','start_us':5000000,'end_us':10000000}
            m['source_reviews']['D1']={'kind':'derived_video','static_ranges':[interval]}
            self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'static intervals'):audit_images(p)
            m['assets'][0]['usage'].append({'segment_id':'operation','type':'derived_video_static','source_id':'D1','start_us':5000000,'end_us':10000000})
            self.save(p,plan,m,s);self.assertEqual(audit_images(p)['derived_static_intervals'],1)
            m['source_reviews']['D1']['kind']='capture';self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'capture cannot'):audit_images(p)
            m['source_reviews']['D1']['kind']='derived_video';m['assets'][0]['usage'][1]['end_us']=11000000;self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'outside consumed'):audit_images(p)
    def test_captured_evidence_is_distinct_from_generated_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p);(p/'recording.mp4').write_bytes(b'unit test capture bytes')
            s['S1']={'id':'S1','path':str(p/'recording.mp4'),'sha256':sha(p/'recording.mp4'),'duration_us':10000000}
            asset=m['assets'][0];asset.update(kind='evidence_capture',lane='source_evidence',mode='capture',evidence={'source_id':'S1','source_sha256':s['S1']['sha256'],'at_us':1000000})
            asset.pop('prompt');asset.pop('conversation_url');self.save(p,plan,m,s)
            self.assertEqual(audit_images(p)['evidence_captures'],1)
            (p/'recording.mp4').write_bytes(b'changed capture')
            with self.assertRaisesRegex(ValueError,'source SHA256'):audit_images(p)
    def test_coverage_and_source_review_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p)
            m['assets'][0]['usage']=[{'segment_id':'unknown','type':'image'}];self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'unknown segment'):audit_images(p)
            plan,m,s=self.fixture_existing(p)
            (p/'capture.mp4').write_bytes(b'capture');s['S1']={'id':'S1','path':str(p/'capture.mp4'),'sha256':sha(p/'capture.mp4'),'duration_us':1000000}
            plan['segments'].append({'id':'capture','source_id':'S1','frames':60,'text':'实拍。'});self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'Missing source review'):audit_images(p)
            m['source_reviews']['S1']={'kind':'capture'};self.save(p,plan,m,s)
            self.assertEqual(audit_images(p)['reviewed_video_sources'],1)
    def fixture_existing(self,p):
        return json.loads((p/'production-plan.json').read_text(encoding='utf-8')),self._fresh_manifest(p),{}
    def _fresh_manifest(self,p):
        return {'version':1,'source_reviews':{},'assets':[{'image_id':'card','lane':'web_chatgpt_chrome','mode':'create_image','conversation_url':'https://chatgpt.com/c/fixture-completed','prompt':{'path':'prompt.txt','sha256':sha(p/'prompt.txt')},'original':{'path':'original.png','sha256':sha(p/'original.png')},'qa':{'facts':'passed','text':'passed','visual':'passed'},'usage':[{'segment_id':'intro','type':'image'}]}]}
    def test_build_stops_before_paid_synthesis_when_manifest_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p);plan.pop('visual_asset_manifest');plan['music']={'mode':'none'};self.save(p,plan,m,s)
            with patch('runtime_env.preflight',return_value={'ready':True}),patch('video.subtitle_ffmpeg',return_value='unused'),patch('video.assemble') as synthesis:
                result=build(p)
            self.assertEqual(result['stage'],'needs_image_audit');synthesis.assert_not_called()
    def test_legacy_validate_does_not_require_or_create_an_image_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);package=p/'delivery/剪映导入包';(package/'audio').mkdir(parents=True);(p/'engineering').mkdir()
            write(package/'draft-plan.json',{'tracks':[]});write(package/'timeline.json',{'total_frames':60,'fps':60,'visuals':[],'cues':[],'sources':[]})
            for name in ['旁白.wav','音乐.wav','混音.wav']:
                with wave.open(str(package/'audio'/name),'wb') as stream:stream.setparams((1,2,48000,0,'NONE',''));stream.writeframes(bytes(96000))
            with patch('draft_backend.build',return_value={}),patch('draft_backend.validate',return_value={'file_validation':'passed'}),patch('draft_backend.app_dir',return_value=p),patch('native_bridge.validate',return_value={'native_read':'passed'}),patch('video.audit_images') as audited:
                result=validate(p)
            self.assertTrue(result['source_unchanged']);audited.assert_not_called();self.assertFalse((p/'engineering/visual-assets.json').exists())

    def test_static_coverage_is_intersected_per_consumed_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p);(p/'composite.mp4').write_bytes(b'unit test source bytes')
            s['D1']={'id':'D1','path':str(p/'composite.mp4'),'duration_us':10000000,'sha256':sha(p/'composite.mp4')}
            m['source_reviews']['D1']={'kind':'derived_video','static_ranges':[{'image_id':'card','start_us':5000000,'end_us':10000000}]}
            plan['segments'].append({'id':'capture_only','frames':240,'source_id':'D1','source_start_us':0,'text':'实拍区间。'})
            self.save(p,plan,m,s);self.assertEqual(audit_images(p)['derived_static_intervals'],0)
            plan['segments'].extend([{'id':'partial','frames':180,'source_id':'D1','source_start_us':4000000,'text':'跨边界。'},
                                     {'id':'repeated','frames':120,'source_id':'D1','source_start_us':6000000,'text':'重复使用。'}])
            m['assets'][0]['usage'].append({'segment_id':'partial','type':'derived_video_static','source_id':'D1','start_us':5000000,'end_us':7000000})
            self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'static intervals'):audit_images(p)
            m['assets'][0]['usage'].append({'segment_id':'repeated','type':'derived_video_static','source_id':'D1','start_us':6000000,'end_us':8000000})
            self.save(p,plan,m,s);self.assertEqual(audit_images(p)['derived_static_intervals'],2)
    def test_images_only_preflight_defers_unrendered_derived_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p)
            s['D1']={'id':'D1','path':str(p/'not-rendered.mp4'),'duration_us':10000000,'sha256':'0'*64}
            plan['segments'].append({'id':'operation','frames':600,'source_id':'D1','text':'操作演示。'})
            m['source_reviews']['D1']={'kind':'derived_video','static_ranges':[{'image_id':'card','start_us':5000000,'end_us':10000000}]}
            m['assets'][0]['usage'].append({'segment_id':'operation','type':'derived_video_static','source_id':'D1','start_us':5000000,'end_us':10000000})
            self.save(p,plan,m,s)
            partial=audit_images(p,images_only=True)
            self.assertEqual(partial['status'],'images_ready');self.assertEqual(partial['deferred_video_sources'],['D1'])
            with self.assertRaisesRegex(ValueError,'source file missing'):audit_images(p)
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('video.py')),'audit-images','--images-only','--project',str(p)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['status'],'images_ready')

    def test_cover_adoption_keeps_downloaded_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p)
            (p/'cover.png').write_bytes((p/'original.png').read_bytes())
            m['assets'][0]['usage'].append({'type':'cover','file':{'path':'cover.png','sha256':sha(p/'cover.png')}})
            self.save(p,plan,m,s);self.assertEqual(audit_images(p)['status'],'passed')
            Image.new('RGB',(16,9),'blue').save(p/'cover.png')
            m['assets'][0]['usage'][1]['file']['sha256']=sha(p/'cover.png');self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'cover differs from original'):audit_images(p)

    def test_standalone_software_screenshot_needs_no_video_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p)
            (p/'screenshot.png').write_bytes((p/'original.png').read_bytes())
            asset=m['assets'][0];asset.update(kind='evidence_capture',lane='source_evidence',mode='capture',evidence={'source_file':{'path':'screenshot.png','sha256':sha(p/'screenshot.png')}})
            asset.pop('prompt');asset.pop('conversation_url');self.save(p,plan,m,s)
            self.assertEqual(audit_images(p)['evidence_captures'],1)
            Image.new('RGB',(16,9),'blue').save(p/'original.png')
            plan['images']['card']['sha256']=sha(p/'original.png');asset['original']['sha256']=sha(p/'original.png');self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'retain original bytes'):audit_images(p)
    def test_standalone_screenshot_crop_verifies_pixels_and_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan,m,s=self.fixture(p)
            (p/'screenshot.png').write_bytes((p/'original.png').read_bytes())
            with Image.open(p/'screenshot.png') as image:image.crop((0,0,8,9)).save(p/'original.png')
            plan['images']['card']['sha256']=sha(p/'original.png');asset=m['assets'][0]
            asset.update(kind='evidence_capture',lane='source_evidence',mode='capture',evidence={'source_file':{'path':'screenshot.png','sha256':sha(p/'screenshot.png')},'crop_box':[0,0,8,9]})
            asset['original']['sha256']=sha(p/'original.png');asset.pop('prompt');asset.pop('conversation_url');self.save(p,plan,m,s)
            self.assertEqual(audit_images(p)['evidence_captures'],1)
            Image.new('RGB',(8,9),'red').save(p/'original.png');plan['images']['card']['sha256']=sha(p/'original.png');asset['original']['sha256']=sha(p/'original.png');self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'preserve source pixels'):audit_images(p)
            asset['evidence']['crop_box']=[-1,0,8,9];self.save(p,plan,m,s)
            with self.assertRaisesRegex(ValueError,'outside source image'):audit_images(p)

if __name__=='__main__':unittest.main()
