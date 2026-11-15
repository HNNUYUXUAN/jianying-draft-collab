"""Explicit cloud acceptance must prove its own account, without unrelated gates."""
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
import cloud_smoke as smoke
import pipeline
from volc_audio import DEFAULTS

class CloudAcceptanceTests(unittest.TestCase):
    def test_fresh_account_check_uses_run_local_tts_cache_and_minimal_prerequisites(self):
        with tempfile.TemporaryDirectory()as d:
            out=Path(d);cfg={**DEFAULTS,'VOLC_AGENT_API_KEY':'fixture-account'};calls=[]
            def tts(text,path,cfg,**kw):
                calls.append(kw['cache_root']);path.parent.mkdir(parents=True,exist_ok=True);pipeline.wav(path,48000,bytes(48000*2))
                pipeline.write(path.with_suffix('.tts.json'),{'words':[{'text':text,'start_ms':0,'end_ms':500}],'timestamp_source':'tts_native','log_id':'fixture-live-request'})
            def asr(placement,cfg):
                row=pipeline.read(placement)['segments'][0]
                pipeline.write(Path(row['audio']).with_suffix('.asr.json'),{'response':{'words':[{'text':row['text'],'start_ms':0,'end_ms':500}],'timestamp_source':'asr_native','log_id':'fixture-asr'}})
            with patch.object(smoke,'config',return_value=cfg),patch('runtime_env.doctor',return_value={'local_ready':True})as doctor,patch('volc_audio.tts',side_effect=tts)as request,patch.object(smoke,'asr',side_effect=asr),patch('vision.analyze',return_value={'id':'fixture-vision','output':[{'content':[{'type':'output_text','text':'blue rectangle'}]}]}):
                result=smoke.run(out)
                self.assertEqual(result['status'],'passed')
                self.assertEqual(calls,[out/'acceptance-tts-cache'])
                doctor.assert_called_with(task='offline',required=['core','media','cloud_config'],require_smoke=False)
                request.assert_called_once()
                again=smoke.run(out)
                self.assertTrue(again['checks']['tts']['reused_completed_acceptance']);request.assert_called_once()
            with patch.object(smoke,'config',return_value={**cfg,'VOLC_AGENT_API_KEY':'changed-fixture-account'}),patch('volc_audio.tts')as request:
                with self.assertRaisesRegex(RuntimeError,'account or configuration changed'):smoke.run(out)
                request.assert_not_called()

    def test_unbound_legacy_success_does_not_verify_a_new_account(self):
        with tempfile.TemporaryDirectory()as d:
            out=Path(d);pipeline.write(out/'cloud-smoke.json',{'checks':{'tts':{'status':'passed'}}})
            with patch.object(smoke,'config',return_value={**DEFAULTS,'VOLC_AGENT_API_KEY':'fixture'}),patch('runtime_env.doctor')as doctor:
                with self.assertRaisesRegex(RuntimeError,'unbound'):smoke.run(out)
                doctor.assert_not_called()

if __name__=='__main__':unittest.main()
