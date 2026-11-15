import copy,json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import native_bridge as n

class NativeBridgeTests(unittest.TestCase):
    def summary(self):
        return {'nodes':[{'id':'track','type':'track','attributes':{'segments':['text','video']}},
          {'id':'text','type':'text'},{'id':'video','type':'video'}]}
    def test_wrong_track_rejected(self):
        with self.assertRaisesRegex(ValueError,'Track/segment'):
            n.commands({'operations':[{'op':'update','track_id':'other','segment_id':'text','changes':{'text':'x'}}]},self.summary())
    def test_unknown_segment_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unknown segment'):
            n.commands({'operations':[{'op':'remove','track_id':'track','segment_id':'unknown'}]},self.summary())
    def test_native_actions_cannot_retarget(self):
        for flag in ('--ref','--dir','--ref=local://other','--action'):
            with self.subTest(flag=flag),self.assertRaises(ValueError):
                n.commands({'native_actions':[['text','content',flag,'x']]},self.summary())
    def test_focus_and_project_delete_not_exposed(self):
        for action in (['project','focus'],['project','delete'],['auth','login']):
            with self.subTest(action=action),self.assertRaises(ValueError):
                n.commands({'native_actions':[action]},self.summary())
    def test_no_float_time_truncation(self):
        with self.assertRaisesRegex(ValueError,'Invalid start'):
            n.commands({'operations':[{'op':'update','track_id':'track','segment_id':'video','changes':{'start_us':1.5}}]},self.summary())
    def test_partial_native_copy_cannot_be_registered(self):
        import draft_backend as d
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);stage=base/'stage';stage.mkdir()
            (stage/'batch-receipt.json').write_text(json.dumps({'backend':'bundled_lyra','state':'prepared','destination':str(base/'projects/final')}))
            with patch.object(d,'running',return_value=False),self.assertRaisesRegex(ValueError,'incomplete'):
                d.install(stage,base/'projects')
            self.assertFalse((base/'projects/final').exists())
    def test_transport_filters_keys_and_uses_no_window(self):
        reply=subprocess.CompletedProcess([],0,b'{"err_code":0,"result":{"ok":true}}',b'')
        with patch.object(n.runtime,'require',return_value={'adapter':{'kind':'bundled_lyra','host':'vebun.exe','cli':'lyra-cli.exe'}}),patch.dict(os.environ,{'VOLC_AGENT_API_KEY':'test-key','BOCHA_API_KEY':'test-key'}),patch.object(n.subprocess,'run',return_value=reply) as call:
            result=n.run(Path('fixture'),['draft','extract'])
            self.assertEqual(result,{'ok':True})
            options=call.call_args.kwargs
            self.assertNotIn('VOLC_AGENT_API_KEY',options['env'])
            self.assertNotIn('BOCHA_API_KEY',options['env'])
            if os.name=='nt':self.assertEqual(options['creationflags'],subprocess.CREATE_NO_WINDOW)
    def test_failed_native_response_is_not_success(self):
        reply=subprocess.CompletedProcess([],1,b'{"err_code":-100147,"err_msg":"postcondition failed","result":null}',b'')
        with patch.object(n.runtime,'require',return_value={'adapter':{'kind':'bundled_lyra','host':'vebun.exe','cli':'lyra-cli.exe'}}),patch.object(n.subprocess,'run',return_value=reply):
            with self.assertRaisesRegex(ValueError,'postcondition failed'):n.run(Path('fixture'),['draft','extract'])
class NativeReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.media=self.root/'sound.wav';self.media.write_bytes(b'fixture media')
        self.before=[
          {'id':'root','type':'draft','attributes':{'width':1920,'height':1080}},
          {'id':'track','type':'track','parent_id':'root','attributes':{'track_index':0,'segments':['text','audio'],'mute':False}},
          {'id':'text','type':'text','parent_id':'root','attributes':{'content':json.dumps({'text':'old','styles':[{'range':[0,3],'size':15,'bold':False,'fill':{'content':{'solid':{'color':[1,1,1]}}}}]}),'font_size':15,'text_alpha':1,'opaque':'keep'},'timeline':{'start.ms':0,'duration.ms':1000,'end.ms':1000}},
          {'id':'audio','type':'audio','parent_id':'root','attributes':{'source':str(self.media),'volume':1,'opaque':'keep'},'timeline':{'start.ms':0,'duration.ms':2000,'end.ms':2000}}]

    def tearDown(self):self.temp.cleanup()

    def changed_text(self):
        after=copy.deepcopy(self.before);doc=json.loads(after[2]['attributes']['content']);doc['text']='changed';doc['styles'][0]['range']=[0,7]
        after[2]['attributes']['content']=json.dumps(doc);return after

    def run_edit(self,after,linked=None):
        source=self.root/'source';source.mkdir();(source/'draft_content.json').write_bytes(b'opaque encrypted fixture')
        (source/'draft_meta_info.json').write_text(json.dumps({'draft_id':'original'}));(source/'unknown.bin').write_bytes(b'unknown stays')
        output=self.root/'stage';destination=self.root/'projects/final'
        def fake_run(app,args,**kwargs):
            if args[:3]==['draft','project','create']:
                output.mkdir();(output/'draft_meta_info.json').write_text(json.dumps({'draft_id':'independent'}))
            return {}
        def fake_inspect(path,app,scope='summary'):
            return {'nodes':copy.deepcopy(after if Path(path).resolve()==output.resolve()else self.before)}
        plan={'operations':[{'op':'update','track_id':'track','segment_id':'text','changes':{'text':'changed'}}]}
        if linked is not None:plan['allowed_linked_changes']=linked
        with patch.object(n.runtime,'require',return_value={}),patch.object(n.runtime,'projects_root',return_value=self.root/'user-projects'),patch.object(n,'run',side_effect=fake_run),patch.object(n,'inspect',side_effect=fake_inspect):
            result=n.edit_copy(source,plan,output,destination,self.root/'app')
        self.assertEqual((source/'draft_content.json').read_bytes(),b'opaque encrypted fixture')
        self.assertEqual((output/'unknown.bin').read_bytes(),b'unknown stays')
        return result,output

    def test_successful_noop_is_retained_for_review(self):
        result,output=self.run_edit(self.before)
        self.assertEqual(result['state'],'needs_native_review')
        self.assertTrue(any(issue['code']=='requested_value_mismatch'for issue in result['edit_verification']['issues']))
        import draft_backend as backend
        with patch.object(backend,'running',return_value=False),self.assertRaisesRegex(ValueError,'incomplete'):
            backend.install(output,self.root/'projects',self.root/'app')

    def test_correct_target_readback_validates(self):
        result,_=self.run_edit(self.changed_text())
        self.assertEqual(result['state'],'validated')
        self.assertTrue(result['edit_verification']['passed'])
        self.assertEqual(result['verified_nodes_sha256'],result['native_validation']['nodes_sha256'])

    def test_unrelated_node_change_blocks_validation(self):
        after=self.changed_text();after[3]['attributes']['volume']=.4
        result,_=self.run_edit(after)
        self.assertEqual(result['state'],'needs_native_review')
        self.assertTrue(any(issue.get('segment_id')=='audio'and issue.get('field')=='attributes.volume'for issue in result['edit_verification']['issues']))

    def test_explicit_linked_field_is_allowed(self):
        after=self.changed_text();after[3]['attributes']['volume']=.4
        result,_=self.run_edit(after,[{'segment_id':'audio','fields':['attributes.volume'],'reason':'Plan intentionally permits the native linked volume adjustment'}])
        self.assertEqual(result['state'],'validated')

    def test_linked_allowance_cannot_hide_wrong_requested_value(self):
        proof=n.verification.verify_intent(self.before,self.before,[['text','content','--seg-id','text','--content','changed']],{'allowed_linked_changes':[{'segment_id':'text','fields':['attributes.content.text'],'reason':'explicit field'}]})
        self.assertFalse(proof['passed'])

    def test_volume_and_time_noops_are_rejected(self):
        for action in [['audio','volume','--seg-id','audio','--linear','0.2'],['segment','move','--seg-id','text','--start','200ms'],['segment','time-range','--seg-id','text','--duration','800ms']]:
            with self.subTest(action=action):self.assertFalse(n.verification.verify_intent(self.before,self.before,[action],{})['passed'])

    def test_audio_add_kind_is_rejected_without_verified_postcondition(self):
        proof=n.verification.verify_intent(self.before,self.before,[['audio','add','--resource',n.ref(self.media),'--kind','sound']],{})
        self.assertFalse(proof['passed'])
        self.assertEqual(proof['issues'][0]['code'],'unverifiable_plan')
        self.assertIn('--kind',proof['issues'][0]['reason'])

    def test_text_style_value_must_be_read_back(self):
        self.assertFalse(n.verification.verify_intent(self.before,self.before,[['text','style','--seg-id','text','--bold','true']],{})['passed'])
        after=copy.deepcopy(self.before);document=json.loads(after[2]['attributes']['content']);document['styles'][0]['bold']=True
        after[2]['attributes']['content']=json.dumps(document)
        self.assertTrue(n.verification.verify_intent(self.before,after,[['text','style','--seg-id','text','--bold','true']],{})['passed'])

    def test_track_muting_is_not_an_implicit_linked_change(self):
        after=self.changed_text();after[1]['attributes']['mute']=True
        self.assertFalse(n.verification.verify_intent(self.before,after,[['text','content','--seg-id','text','--content','changed']],{})['passed'])

    def test_color_and_alpha_verify_derived_native_fields(self):
        after=copy.deepcopy(self.before);attrs=after[2]['attributes'];document=json.loads(attrs['content']);style=document['styles'][0]
        style['fill']['content']['solid']['color']=[.2,.4,.6];style['fill']['alpha']=.8;style['useLetterColor']=True
        attrs.update(content=json.dumps(document),font_color='#336699FF',text_alpha=.8)
        action=['text','style','--seg-id','text','--color','#336699','--alpha','0.8']
        self.assertTrue(n.verification.verify_intent(self.before,after,[action],{})['passed'])
        style['fill']['alpha']=.2;attrs['content']=json.dumps(document)
        self.assertFalse(n.verification.verify_intent(self.before,after,[action],{})['passed'])

    def test_structurally_invalid_native_read_is_not_validation(self):
        duplicate=self.before+[copy.deepcopy(self.before[2])]
        with patch.object(n,'inspect',return_value={'nodes':duplicate}),self.assertRaisesRegex(ValueError,'unique'):
            n.validate(self.root/'draft',self.root/'app')

    def test_validated_stage_change_is_detected_before_install(self):
        folder=self.root/'stage';folder.mkdir()
        (folder/'batch-receipt.json').write_text(json.dumps({'backend':'bundled_lyra','state':'validated','verified_nodes_sha256':n.verification.nodes_sha256(self.before)}))
        with patch.object(n,'inspect',return_value={'nodes':self.changed_text()}),self.assertRaisesRegex(ValueError,'stale'):
            n.validate(folder,self.root/'app')


if __name__=='__main__':unittest.main(verbosity=2)
