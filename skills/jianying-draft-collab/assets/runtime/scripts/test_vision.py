import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import vision

class VisionTests(unittest.TestCase):
    def test_completed_cache_and_pending_guard(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);f=p/'frame.png';Image.new('RGB',(8,8)).save(f)
            class Response:
                status_code=200
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def iter_lines(self):yield b'data: '+json.dumps({'type':'response.completed','response':{'status':'completed','id':'test'}}).encode()
            with patch('vision.config',return_value={'VOLC_AGENT_API_KEY':'fixture'}),patch('vision.requests.post',return_value=Response()) as post:
                self.assertEqual(vision.analyze([f],'task',p/'cache')['id'],'test')
                vision.analyze([f],'task',p/'cache');self.assertEqual(post.call_count,1)
                post.side_effect=RuntimeError('interrupted')
                with self.assertRaises(RuntimeError):vision.analyze([f],'other',p/'cache')
                with self.assertRaises(ValueError):vision.analyze([f],'other',p/'cache')
                self.assertEqual(post.call_count,2)
if __name__=='__main__':unittest.main()
