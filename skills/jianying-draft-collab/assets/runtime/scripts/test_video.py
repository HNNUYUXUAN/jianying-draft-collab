import unittest,tempfile,wave,os
from pathlib import Path
import numpy as np
from captions import display,clauses,reflow
from music import envelope,create,speech_intervals
from video import validate_plan,hlg_to_709_filter
from unittest.mock import patch
from music_adapter import ROOT
FF=Path(os.environ.get('JIANYING_TEST_FFMPEG',str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe')))

class VideoTests(unittest.TestCase):
    def test_caption_display_keeps_numbers_and_internal_marks(self):
        for raw,want in [('速度为1.5m/s。','速度为1.5m/s'),('先调零，再发射！','先调零，再发射'),('a=-9.8m/s²……','a=-9.8m/s²'),('为什么？','为什么')]:self.assertEqual(display(raw),want)
        self.assertEqual(clauses('保持匀速，竖直自由落体。'),['保持匀速，','竖直自由落体。'])
    def test_multi_source_duration_and_range_contract(self):
        sources={'a':{'duration_us':200000000},'b':{'duration_us':200000000}}
        for seconds in [90,120,150]:
            plan={'version':1,'fps':60,'segments':[{'id':'a','frames':seconds*30,'source_id':'a'},{'id':'b','frames':seconds*30,'source_id':'b'}]}
            self.assertEqual(len(validate_plan(plan,sources)),2)
        with self.assertRaises(AssertionError):validate_plan({'version':1,'segments':[{'id':'x','frames':7200,'source_id':'a','source_start_us':199999999}]},sources)
    def test_explicit_duration_range_boundaries_and_material_driven_default(self):
        sources={'a':{'duration_us':600000000}}
        def plan(seconds,limits=None):
            value={'version':1,'fps':60,'segments':[{'id':'a','frames':round(seconds*60),'source_id':'a'}]}
            if limits is not None:value['duration_range_seconds']=limits
            return value
        for seconds in [300,390,480]:self.assertEqual(len(validate_plan(plan(seconds,[300,480]),sources)),1)
        for seconds in [299+59/60,480+1/60]:
            with self.assertRaises(AssertionError):validate_plan(plan(seconds,[300,480]),sources)
        for seconds in [12,89,90,120,150,151,300,390]:self.assertEqual(len(validate_plan(plan(seconds),sources)),1)
        with self.assertRaises(AssertionError):validate_plan(plan(0),sources)
        for limits in [[],[300],[300,480,600],[480,300],[0,480],[True,480],['300',480],[300,float('inf')]]:
            with self.assertRaises(AssertionError):validate_plan(plan(390,limits),sources)
    def test_hlg_tone_map_is_conditional_and_validates_input_tags(self):
        stream={'codec_type':'video','color_transfer':'bt709','color_primaries':'bt709','color_space':'bt709','color_range':'tv'}
        with patch('video.probe',return_value={'streams':[stream]}):self.assertEqual(hlg_to_709_filter('sdr.mp4'),'')
        stream.update(color_transfer='arib-std-b67',color_primaries='bt2020',color_space='bt2020nc')
        with patch('video.probe',return_value={'streams':[stream]}):
            vf=hlg_to_709_filter('hlg.mp4')
            self.assertIn('transferin=arib-std-b67',vf)
            self.assertIn('matrixin=bt2020nc:rangein=limited',vf)
            self.assertIn('tonemap=tonemap=hable:desat=0',vf)
        stream['color_primaries']='bt709'
        with patch('video.probe',return_value={'streams':[stream]}):
            with self.assertRaises(ValueError):hlg_to_709_filter('mismatched.mp4')
    def test_envelope_restores_long_gap_not_short_word_gap(self):
        e=envelope(480000,[(1,2),(2.2,3),(7,8)])
        self.assertAlmostEqual(float(e[60000]),10**(-8/20),places=5)
        self.assertAlmostEqual(float(e[105600]),10**(-8/20),places=5)
        self.assertAlmostEqual(float(e[240000]),1,places=5)
        self.assertTrue(np.max(np.abs(np.diff(e)))<.001)
    @unittest.skipUnless(FF.is_file(),'Dedicated FFmpeg not prepared')
    def test_actual_music_pcm_and_true_peak(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);data=np.zeros(240000,dtype=np.int16);t=np.arange(48000)/48000;data[24000:72000]=np.round(np.sin(2*np.pi*220*t)*8000).astype(np.int16)
            with wave.open(str(p/'voice.wav'),'wb') as w:w.setparams((1,2,48000,0,'NONE',''));w.writeframes(data.tobytes())
            cues=[{'start_ms':500,'end_ms':1500}];r=create(p/'voice.wav',cues,p/'out',{'mode':'none'},ffmpeg=FF)
            self.assertEqual(r['samples'],240000);self.assertLessEqual(float(r['mix_measurement']['input_tp']),-1)
            self.assertEqual(create(p/'voice.wav',cues,p/'out',{'mode':'none'},ffmpeg=FF)['identity'],r['identity'])
    def test_silence_inside_a_cue_is_detected(self):
        x=np.zeros((240000,2));x[24000:72000]=.2
        intervals=speech_intervals(x,[{'start_ms':0,'end_ms':5000}])
        e=envelope(len(x),intervals)
        self.assertEqual(float(e[180000]),1)
    def test_reflow_rejects_math_rewrites(self):
        placement={'segments':[{'id':'x','text':'加速度为-9.8m/s²。'}]}
        audit={'segments':[{'chars':[],'offset_ms':0}]}
        for changed in ['加速度为9.8m/s²。','加速度为-98m/s²。']:
            with self.assertRaises(AssertionError):reflow(placement,audit,{'x':[changed]})
if __name__=='__main__':unittest.main()
