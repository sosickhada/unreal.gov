"""Exercise the real process boundary without launching Chromium or touching public files."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch
from bureau.config import Config
from bureau.adapters import Media,ExternalError


class RenderBoundaryTests(unittest.TestCase):
    def test_completed_capture_survives_shutdown_timeout(self):
        import json
        from PIL import Image
        with tempfile.TemporaryDirectory() as root:
            paths=[]
            for i in range(5):
                p=Path(root)/f'page-{i}.png';Image.new('RGB',(1080,1350)).save(p);paths.append(str(p))
            process=Mock(pid=999999)
            process.wait.side_effect=[subprocess.TimeoutExpired('renderer',1),-9]
            def spawn(args,**kw):
                Path(args[-1]).write_text(json.dumps(paths));return process
            config=Config(Path(root)/'db',{'IMAGE_DIR':root,'PUBLIC_BASE_URL':'https://media.example','RENDER_TIMEOUT_SECONDS':'1'})
            with patch('subprocess.Popen',side_effect=spawn),patch('bureau.adapters.terminate_render_tree') as cleanup:
                result=Media(config).render({},1,1)
            cleanup.assert_called_once_with(process.pid)
            self.assertEqual(len(result['files']),5)

    def test_hung_chromium_child_group_is_killed(self):
        with tempfile.TemporaryDirectory() as root:
            config=Config(Path(root)/'db',{'IMAGE_DIR':root,'PUBLIC_BASE_URL':'https://media.example','RENDER_TIMEOUT_SECONDS':'1'})
            process=Mock(pid=999999)
            process.wait.side_effect=[subprocess.TimeoutExpired('renderer',1),-9]
            with patch('subprocess.Popen',return_value=process),patch('os.killpg') as kill:
                with self.assertRaisesRegex(ExternalError,'hard deadline'):
                    Media(config).render({'slides':[]},1,1)
                kill.assert_called_once()
                self.assertEqual(process.wait.call_count,2)
    def test_child_failure_is_redacted(self):
        with tempfile.TemporaryDirectory() as root:
            config=Config(Path(root)/'db',{'IMAGE_DIR':root,'PUBLIC_BASE_URL':'https://media.example'})
            process=Mock(pid=999999);process.wait.return_value=1
            with patch('subprocess.Popen',return_value=process):
                with self.assertRaisesRegex(ExternalError,'Figma render failed'):Media(config).render({},1,1)

if __name__=='__main__':unittest.main()
