"""One owned private-Python worker; cooperative stop preserves training outputs."""
import json
from pathlib import Path
import subprocess
from threading import Thread
from uuid import uuid4

from PySide6.QtCore import QObject, Signal
from app.paths import PROJECT_ROOT
from app.services.owned_process import spawn_hidden
from app.updates.manifest import atomic_json
from scripts.start_tts import service_environment


class TrainingJob(QObject):
    event = Signal(object)
    finished = Signal(object)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = Path(service)
        self.training = self.service / 'training'
        self.thread = self.process = self.job = None
        self.directory = None
        self.before_start = None

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, project, task, options, **extra):
        if self.running:
            raise ValueError('已有训练任务正在运行，请先等待完成或停止')
        options.validate()
        directory = project.directory / 'jobs' / uuid4().hex
        directory.mkdir(parents=True)
        request = dict(project=str(project.directory), service=str(self.service), training=str(self.training), task=task,
                       options=vars(options), **extra)
        atomic_json(directory / 'request.json', request)
        self.directory = directory
        self.thread = Thread(target=self._run, args=(directory,), daemon=True)
        self.thread.start()

    def _run(self, directory):
        outcome = dict(ok=False, error='', task='', log=str(directory / 'worker.log'))
        try:
            if (directory / 'stop.request').exists():
                outcome.update(ok=True, stopped=True)
                return
            if self.before_start:
                self.before_start()
            if (directory / 'stop.request').exists():
                outcome.update(ok=True, stopped=True)
                return
            env = service_environment(self.service)
            env.update(PYTHONUNBUFFERED='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                       TACHITALK_TTS_WARMUP='0')
            command = [str(self.service / 'runtime/python.exe'), '-u', '-B',
                       str(PROJECT_ROOT / 'scripts/training_worker.py'), '--request', str(directory / 'request.json')]
            self.process, self.job = spawn_hidden(command, cwd=self.service, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            with (directory / 'worker.log').open('w', encoding='utf-8') as log:
                for raw in iter(self.process.stdout.readline, b''):
                    line = raw.decode('utf-8', errors='replace').rstrip()
                    log.write(line + '\n')
                    log.flush()
                    if line.startswith('TACHITALK_EVENT '):
                        try:
                            self.event.emit(json.loads(line[16:]))
                        except ValueError:
                            pass
                    elif line:
                        self.event.emit(dict(phase='log', text=line))
            code = self.process.wait()
            result = directory / 'result.json'
            if result.is_file():
                outcome.update(json.loads(result.read_text(encoding='utf-8')))
            else:
                outcome['error'] = f'任务进程已退出（{code}），请查看日志'
            if code and outcome.get('ok'):
                outcome.update(ok=False, error=f'任务进程异常退出（{code}）')
        except Exception as error:
            outcome.update(error=f'{type(error).__name__}: {error}')
        finally:
            if self.job:
                self.job.close()
            self.job = self.process = None
            self.finished.emit(outcome)

    def request_stop(self):
        if self.running:
            (self.directory / 'stop.request').touch()

    def close(self):
        # The UI refuses to quit with an active job; never silently kill it here.
        if not self.running and self.job:
            self.job.close()
