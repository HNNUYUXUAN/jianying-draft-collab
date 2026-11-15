"""Offline numeric BGM regression; activity fixtures are tones, not recorded speech."""
import json,os,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch
import numpy as np
import music_v2 as music
from music_adapter import ROOT,MusicPlanRequired,doctor,plan_ready,source_spec,example_score_path,render_score
from music_fixtures import activity_fixture
from pipeline import fingerprint,sha,write

FF=Path(os.environ.get('JIANYING_TEST_FFMPEG',str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe')))

class MusicNumericTests(unittest.TestCase):
    def arrays(self,n=48000*12):
        t=np.arange(n)/48000
        v=np.zeros(n,dtype=np.float32)
        for a,b,level in [(.75,2.25,.14),(2.5,3.5,.055),(8,9.5,.1)]:
            mask=(t>=a)&(t<b);v[mask]=level*np.sin(2*np.pi*233*t[mask])
        m=.28*np.sin(2*np.pi*330*t)+.1*np.sin(2*np.pi*493*t)
        return np.column_stack((v,v)),np.column_stack((m,m)).astype(np.float32)

    def test_relative_source_paths_and_explicit_modes(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);f=p/'score.json';f.write_text('{"schema":"music-production/v1"}')
            self.assertEqual(source_spec({'score':'score.json'},p)['score'],str(f.resolve()))
            self.assertFalse(plan_ready({},p)['ready'])
            self.assertFalse(plan_ready({'duck_db':10},p)['ready'])
            self.assertTrue(plan_ready({'mode':'none'},p)['ready'])
            self.assertEqual(doctor({'mode':'file'},root=p)['status'],'passed')
            with self.assertRaises(ValueError):source_spec({'mode':'unknown'},p)
            with self.assertRaises(ValueError):source_spec({'runtime':{'python':'untrusted.exe'}},p)

    def test_ducking_protects_soft_activity_and_holds_short_pauses(self):
        v,m=self.arrays();cues=[{'start_ms':750,'end_ms':2250},{'start_ms':2500,'end_ms':3500},{'start_ms':8000,'end_ms':9500}]
        before=v.copy();automated,report=music.mix_arrays(v,m,cues,{'fade_in_ms':0,'fade_out_ms':0})
        self.assertTrue(np.array_equal(v,before));self.assertEqual(automated.shape,v.shape)
        vr=music._rms(v,24000);mr=music._rms(automated,24000);gap=(vr-mr)[vr>-35]
        self.assertGreaterEqual(float(np.percentile(gap,10)),25.9)
        env=np.array(report['envelope_20ms']['gain_db'])
        self.assertLessEqual(env[round(2.35*50)],max(env[round(2*50)],env[round(2.75*50)])+.2)
        self.assertGreater(env[round(6.5*50)],env[round(3*50)]+8)
        self.assertLessEqual(float(np.diff(env).max()),6/50+1e-7)
        self.assertGreaterEqual(float(np.diff(env).min()),-37.5/50-1e-7)

    def test_pcm_outside_caption_is_also_protected_and_partial_tail_kept(self):
        v,m=self.arrays(48000*12+137)
        automated,report=music.mix_arrays(v,m,[])
        self.assertEqual(len(automated),len(v));self.assertTrue(report['active_intervals'])
        vr=music._rms(v,24000);mr=music._rms(automated,24000)
        self.assertGreaterEqual(float(np.percentile((vr-mr)[vr>-35],10)),25.9)

    def test_bad_parameters_and_nonfinite_pcm_are_rejected(self):
        v,m=self.arrays()
        for options in [{'recovery_db_per_second':-1},{'target_gap_db':10},{'gap_ms':float('nan')},{'bogus':1}]:
            with self.assertRaises(ValueError):music.mix_arrays(v,m,[],options)
        v[1,0]=np.nan
        with self.assertRaises(ValueError):music.mix_arrays(v,m,[])

    def test_legacy_cache_is_reused_only_with_matching_input_fingerprint(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);voice=p/'voice.wav';activity_fixture(voice,3);out=p/'out';out.mkdir()
            lock=json.loads((ROOT/'music-toolchain.json').read_text(encoding='utf-8'))['legacy_cache']
            cues=[{'start_ms':750,'end_ms':2250}]
            identity=fingerprint({'version':1,'implementation':lock['implementation_sha256'],'synth':lock['synth_sha256'],'dialogue':sha(voice),'cues':cues,'recipe':lock['recipe'],'options':music.LEGACY_DEFAULTS})
            for name in music.FILES:(out/name).write_bytes(voice.read_bytes())
            write(out/'music-receipt.json',{'identity':identity,'recipe':{'source':'vendor/music_synth.py; MUSIC_LICENSE'},'mix_measurement':{'input_tp':'-4'}})
            result=music.legacy_cache(voice,cues,out)
            self.assertEqual(result['identity'],identity)
            self.assertIsNone(music.legacy_cache(voice,[{'start_ms':0,'end_ms':100}],out))
            self.assertIsNone(music.legacy_cache(voice,cues,out,{'duck_db':10}))

    @unittest.skipUnless(FF.is_file(),'Dedicated FFmpeg not prepared; set JIANYING_TEST_FFMPEG for local integration')
    def test_file_none_cache_and_exact_voice_bytes(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);voice=p/'voice.wav';cues=activity_fixture(voice,12)
            t=np.arange(48000*12)/48000;source=p/'provided.wav'
            music._write_pcm(source,np.column_stack((.2*np.sin(2*np.pi*330*t),.2*np.sin(2*np.pi*330*t))))
            spec={'mode':'file','file':str(source)}
            r=music.create(voice,cues,p/'out',spec,ffmpeg=FF)
            self.assertEqual((p/'out/dialogue.wav').read_bytes(),voice.read_bytes())
            self.assertGreaterEqual(r['voice_minus_music_500ms_db_percentiles_10_50_90'][0],25.9)
            self.assertLessEqual(float(r['mix_measurement']['input_tp']),-1)
            with wave.open(str(p/'out/bgm.wav'))as stream:self.assertEqual(stream.getnframes(),48000*12)
            with patch.object(music,'_decode',side_effect=AssertionError('Unchanged mix should be reused')):
                self.assertTrue(music.create(voice,cues,p/'out',spec,ffmpeg=FF)['cache_hit'])
            none=music.create(voice,cues,p/'none',{'mode':'none'},ffmpeg=FF)
            self.assertIsNone(none['voice_minus_music_500ms_db_min'])
            self.assertTrue(none['voice_bytes_preserved'])

    @unittest.skipUnless(FF.is_file(),'Dedicated FFmpeg not prepared')
    def test_supplied_music_duration_mismatch_is_not_silently_cut(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);voice=p/'voice.wav';cues=activity_fixture(voice,3);source=p/'short.wav'
            music._write_pcm(source,np.zeros((48000,2),np.float32))
            with self.assertRaises(MusicPlanRequired):music.create(voice,cues,p/'out',{'mode':'file','file':str(source)},ffmpeg=FF)

if __name__=='__main__':unittest.main()
