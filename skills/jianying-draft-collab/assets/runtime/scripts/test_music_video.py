"""Production gates: missing music or failed preflight never starts paid narration."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from pipeline import write,sha
from music_adapter import MusicPlanRequired
from video import build

class MusicVideoGates(unittest.TestCase):
    def project(self,p,music=None):
        (p/'engineering').mkdir();source=p/'source.mp4';source.write_bytes(b'local test source; no decoding needed for gate checks')
        plan={'version':1,'fps':60,'duration_range_seconds':[1,20],'segments':[{'id':'a','frames':120,'source_id':'s','text':'测试讲解'}]}
        if music is not None:plan['music']=music
        write(p/'production-plan.json',plan);write(p/'sources.json',[{'id':'s','path':str(source),'sha256':sha(source),'duration_us':2000000}])

    def test_missing_score_stops_before_preflight_or_narration(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);self.project(p)
            with patch('video.config',return_value={}),patch('video.assemble')as narration,patch('runtime_env.preflight',create=True)as preflight:
                self.assertEqual(build(p)['stage'],'needs_music_plan');narration.assert_not_called();preflight.assert_not_called()

    def test_failed_preflight_stops_before_narration(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);self.project(p,{'mode':'none'})
            with patch('video.config',return_value={}),patch('video.assemble')as narration,patch('runtime_env.preflight',return_value={'ready':False,'failed':['native']},create=True):
                with self.assertRaisesRegex(RuntimeError,'Environment incomplete'):build(p)
                narration.assert_not_called()

    def test_score_review_is_resolved_before_narration(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);score=p/'score.json';score.write_text('{"schema":"music-production/v1"}');self.project(p,{'mode':'score','score':'score.json'})
            with patch('video.config',return_value={}),patch('video.assemble')as narration,patch('runtime_env.preflight',return_value={'ready':True},create=True),patch('music_adapter.prepare_score',side_effect=MusicPlanRequired('Review the unresolved harmony')):
                self.assertEqual(build(p)['stage'],'needs_music_plan');narration.assert_not_called()

    def test_changed_music_for_existing_draft_requires_new_version(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);self.project(p,{'mode':'none'});(p/'delivery/剪映草稿').mkdir(parents=True);write(p/'engineering/native.json',{'identity':'old','music_identity':'old'})
            with patch('video.config',return_value={}),patch('video.assemble')as narration,patch('runtime_env.preflight',create=True)as preflight:
                with self.assertRaisesRegex(ValueError,'new project version'):build(p)
                narration.assert_not_called();preflight.assert_not_called()

if __name__=='__main__':unittest.main()
