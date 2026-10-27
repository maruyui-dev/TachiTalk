"""Real Windows MAX_PATH regression, without changing machine registry settings."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


CHILD = r'''
import hashlib, io, json, os, sys, zipfile
from pathlib import Path
from app.updates.install import apply_archive, recover, uninstall_voice
from app.updates.cleanup import cleanup_committed
from app.updates.manifest import atomic_json
from tests.test_updates import bundle

root = Path(sys.argv[1])
root.mkdir(parents=True)
(root/'TachiTalk.exe').write_bytes(b'fixture')
atomic_json(root/'release-version.json', {'version':'2.0.0'})
name = ('services/gpt_sovits/runtime/Lib/site-packages/modelscope/models/cv/'
        'abnormal_object_detection/mmdet_ms/roi_head/roi_extractors/single_level_roi_extractor.py')
payload, data = bundle('voice', b'new runtime', '*', name)
cache = root/'user_data/updates/downloads'/payload['archive']['sha256']
cache.mkdir(parents=True)
archive = cache/'package.zip'; archive.write_bytes(data)
personal = root/'user_data/personal.txt'; personal.write_bytes(b'personal sentinel')
final = root/name
stage = root/'.tachitalk-transactions'/('a'*32)/'stage'/name
assert len(str(stage)) > 260
events=[]
try:
    transaction = apply_archive(root, archive, payload,
        progress=lambda phase,*a,**k:events.append(phase))
    assert final.read_bytes() == b'new runtime'
    assert cleanup_committed(root)['complete']
    assert not archive.exists()
    assert not transaction.exists()
    # Repair creates a long backup path. An interrupted replacement must restore it.
    archive.parent.mkdir(parents=True,exist_ok=True);archive.write_bytes(data)
    final.write_bytes(b'original runtime')
    def fault(*a): raise RuntimeError('injected replacement failure')
    try: apply_archive(root,archive,payload,fault=fault)
    except RuntimeError as error: assert str(error)=='injected replacement failure'
    else: raise AssertionError('fault did not run')
    assert final.read_bytes() == b'original runtime'
    assert not (root/'.tachitalk-pending.json').exists()
    assert archive.read_bytes()==data
    assert personal.read_bytes()==b'personal sentinel'
    # Uninstall must use the same long-path IO and preserve user content.
    apply_archive(root,archive,payload)
    assert cleanup_committed(root)['complete']
    uninstall_voice(root)
    assert not final.exists()
    assert cleanup_committed(root)['complete']
    assert personal.read_bytes()==b'personal sentinel'
    print(json.dumps({'ok':True,'stage_length':len(str(stage)),
        'final_length':len(str(final)),'events':events}))
except Exception:
    import traceback
    traceback.print_exc()
    raise
'''


@unittest.skipUnless(os.name == 'nt', 'Windows path limit regression')
class WindowsLongInstallPathsTests(unittest.TestCase):
    def test_install_repair_rollback_cleanup_and_uninstall_without_long_path_opt_in(self):
        from PyInstaller.utils.win32.winmanifest import (
            read_manifest_from_executable, write_manifest_to_executable)
        project = Path(__file__).resolve().parents[1]
        with TemporaryDirectory(prefix='long-path-', dir=project/'work') as temporary:
            directory = Path(temporary)
            executable = directory/'legacy-python.exe'
            shutil.copyfile(Path(sys.base_prefix)/'python.exe', executable)
            manifest = read_manifest_from_executable(str(executable))
            if isinstance(manifest, tuple):
                manifest = manifest[1]
            self.assertIn(b'>true</', manifest)
            manifest = manifest.replace(b'>true</', b'>false</')
            write_manifest_to_executable(str(executable), manifest)
            # This child has MAX_PATH enforced even on our long-path-enabled host.
            for dll in ('python312.dll', 'python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
                source = Path(sys.base_prefix)/dll
                if source.is_file():
                    shutil.copyfile(source, directory/dll)
            script = directory/'run.py'
            script.write_text(CHILD, encoding='utf-8')
            env = os.environ.copy()
            env['PYTHONHOME'] = sys.base_prefix
            env['PYTHONPATH'] = os.pathsep.join((str(project),str(Path(sys.prefix)/'Lib/site-packages')))
            # Final file <260, transaction stage/backup >260: the reported r5 failure.
            # Match the reported root length (43), so it fails opening a 267-char file.
            root = directory/('a'*(43-len(str(directory))-1))
            self.assertEqual(len(str(root)),43)
            result = subprocess.run([str(executable),'-B',str(script),str(root)],
                cwd=project,env=env,capture_output=True,text=True,timeout=45)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            record=json.loads(result.stdout.splitlines()[-1])
            self.assertTrue(record['ok'])
            self.assertGreater(record['stage_length'],260)


class FailurePhaseTests(unittest.TestCase):
    def test_failed_install_restart_preserves_failure_phase_and_file(self):
        from argparse import Namespace
        from unittest.mock import patch
        from app.updates.progress import InstallProgress
        from scripts import update_entry
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'TachiTalk.exe').write_bytes(b'fixture')
            result=root/'install-result.json'
            args=Namespace(restart=True,show_progress=True,result=str(result))
            with InstallProgress(result,root) as progress:
                progress.report('install',42,100,current='services/gpt_sovits/runtime/file.py',
                                files_done=12,files_total=40)
                with patch.object(update_entry.subprocess,'Popen'):
                    update_entry.complete_install(args,root,progress,
                        (False,True,False,'FileNotFoundError: fixture',None))
                state=progress.state
            self.assertEqual(state['status'],'failed')
            self.assertEqual(state['phase'],'install')
            self.assertEqual(state['current'],'services/gpt_sovits/runtime/file.py')
            self.assertEqual(state['completed'],42)
            self.assertTrue(state['restarted'])


if __name__ == '__main__':
    unittest.main()
