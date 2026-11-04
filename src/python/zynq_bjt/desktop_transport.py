"""Authenticated SSH transport for the desktop's private stdio worker."""
from concurrent.futures import Future
from pathlib import Path, PurePosixPath
import base64
import hashlib
import io
import json
import shlex
import socket
import threading
import time
import zipfile

from .desktop_agent import PREFIX
from .desktop_session import Session


def agent_archive(source):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
        # Exclude GUI/SSH dependencies from the board process.
        for p in sorted(Path(source).glob('*.py')):
            if p.name in ('curve_export.py','desktop_lcd.py','lcd_records.py'):continue
            if p.name not in ('desktop.py', 'desktop_output.py', 'desktop_transport.py', 'desktop_verify.py', 'scope_view.py', 'meter_view.py', 'parameter_view.py', 'sidebar_art.py', 'workbench_tools.py', 'ai_client.py', 'pdf_view.py', 'datasheet_grid.py', 'metric_strip.py', 'measurement_views.py'):
                info = zipfile.ZipInfo('zynq_bjt/' + p.name, (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, p.read_bytes())
        archive.writestr('__main__.py', 'from zynq_bjt.desktop_agent import main\nraise SystemExit(main())\n')
    return result.getvalue()


class LocalTransport:
    simulated = True
    def __init__(self, data, results, emit=lambda kind, value: None):
        self.session = Session(data, results, simulated=True)
        self.emit = emit
        self.alive = True

    def call(self, op, args=None, timeout=120):
        return self.session.dispatch(op, args, self.emit)

    def prepare(self): self.session.cancel.clear()
    def cancel(self): self.session.cancel.set()
    def fetch(self, result, target): return Path(result['directory'])
    def close(self):
        value = self.session.close()
        self.alive = False
        return value


class SshTransport:
    simulated = False
    def __init__(self, emit=lambda kind, value: None):
        self.emit = emit
        self.client = None
        self.channel = None
        self.alive = False
        self.pending = {}
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.counter = 0
        self.stderr_tail = ''
        self.remote_root = None
        self.fingerprint = None
        self.new_host = False
        self.last_reply = time.monotonic()

    def connect(self, host, user, password, known_hosts, data, archive, *, timeout=10, bitfile=None):
        import paramiko
        known_hosts = Path(known_hosts)
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        client = paramiko.SSHClient()
        if known_hosts.exists(): client.load_host_keys(str(known_hosts))
        owner = self
        class PinFirstHost(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, client, hostname, key):
                # First-use pinning for the user's directly attached board.
                # Existing key changes are rejected by Paramiko before here.
                owner.new_host = True
                client.get_host_keys().add(hostname, key.get_name(), key)
        client.set_missing_host_key_policy(PinFirstHost())
        try:
            client.connect(host, username=user, password=password, look_for_keys=False,
                           allow_agent=False, timeout=timeout, auth_timeout=timeout, banner_timeout=timeout)
            client.save_host_keys(str(known_hosts))
            key = client.get_transport().get_remote_server_key()
            self.fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
            # Package + data are deployed under the SSH account, never over the
            # installed PYNQ package, notebook, bitstream or system service.
            data_files = {p.name: p.read_bytes() for p in Path(data).glob('*.json')}
            digest = hashlib.sha256(archive + b''.join(data_files[n] for n in sorted(data_files))).hexdigest()[:20]
            with client.open_sftp() as sftp:
                home = sftp.normalize('.')
                root = home + '/.zynq_bjt_desktop'
                for directory in (root, root+'/'+digest, root+'/'+digest+'/data', root+'/results'):
                    try: sftp.stat(directory)
                    except IOError: sftp.mkdir(directory)
                self.remote_root = root
                agent = root+'/'+digest+'/agent.pyz'
                with sftp.open(agent, 'wb') as f: f.write(archive)
                for name, content in data_files.items():
                    with sftp.open(root+'/'+digest+'/data/'+name, 'wb') as f: f.write(content)
            script = ('source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; '
                      'export PYTHONUNBUFFERED=1; exec python -u {} --data {} --results {}').format(
                          shlex.quote(agent), shlex.quote(root+'/'+digest+'/data'), shlex.quote(root+'/results'))
            if bitfile is not None:script+=' --bitfile '+shlex.quote(str(bitfile))
            channel = client.get_transport().open_session(timeout=timeout)
            channel.settimeout(5)
            channel.exec_command("sudo -S -p '' bash -c " + shlex.quote(script))
            channel.sendall((password+'\n').encode())
            self.client, self.channel, self.alive = client, channel, True
            self.last_reply = time.monotonic()
            threading.Thread(target=self._receive, daemon=True).start()
            threading.Thread(target=self._heartbeat, daemon=True).start()
            value = self.call('status', timeout=30)
            value.update(ssh_fingerprint=self.fingerprint, first_connection=self.new_host)
            return value
        except BaseException:
            self.abort()
            client.close()
            raise

    def prepare(self): pass

    def _send(self, message):
        if not self.alive: raise ConnectionError('连接已断开；板端输出状态未知')
        data = (json.dumps(message, ensure_ascii=True, allow_nan=False)+'\n').encode()
        with self.send_lock: self.channel.sendall(data)

    def call(self, op, args=None, timeout=120):
        with self.lock:
            self.counter += 1
            number = self.counter
            future = Future()
            self.pending[number] = future
        try:
            self._send({'id': number, 'op': op, 'args': args or {}})
            return future.result(timeout=timeout)
        except TimeoutError as error:
            self.abort()
            raise TimeoutError('板端响应超时；停止确认未收到，输出状态未知') from error
        finally:
            with self.lock: self.pending.pop(number, None)

    def cancel(self): self._send({'op': 'cancel'})

    def _heartbeat(self):
        while self.alive:
            if time.monotonic() - self.last_reply > 16:
                self._fail('16 秒未收到板端心跳，输出状态未知')
                self.channel.close()
                break
            try: self._send({'op': 'heartbeat'})
            except Exception as error: self._fail(str(error)); break
            time.sleep(2)

    def _receive(self):
        buffer = b''
        try:
            while self.alive:
                if self.channel.recv_stderr_ready():
                    text = self.channel.recv_stderr(65536).decode('utf-8', 'replace')
                    self.stderr_tail = (self.stderr_tail+text)[-4000:]
                if self.channel.recv_ready():
                    block = self.channel.recv(65536)
                    if not block: break
                    buffer += block
                    if len(buffer) > 16000000: raise ValueError('板端响应过长')
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        text = line.decode('utf-8', 'replace')
                        if not text.startswith(PREFIX):
                            if text.strip(): self.emit('log', text)
                            continue
                        message = json.loads(text[len(PREFIX):])
                        self.last_reply = time.monotonic()
                        if 'event' in message:
                            if message['event'] != 'heartbeat': self.emit(message['event'], message.get('value'))
                        else:
                            with self.lock: future = self.pending.get(message.get('id'))
                            if future is not None and not future.done():
                                if message.get('ok'): future.set_result(message.get('value'))
                                else: future.set_exception(RuntimeError(message.get('error', '板端操作失败')))
                elif self.channel.exit_status_ready(): break
                else: time.sleep(.02)
        except Exception as error:
            self._fail(str(error))
        finally:
            if self.alive: self._fail('SSH 会话已结束。'+self.stderr_tail)

    def _fail(self, reason):
        was_alive, self.alive = self.alive, False
        with self.lock: futures = list(self.pending.values())
        for future in futures:
            if not future.done(): future.set_exception(ConnectionError(reason))
        if was_alive: self.emit('connection_lost', reason)

    def fetch(self, result, target):
        run_id = result['run_id']
        if PurePosixPath(run_id).name != run_id or run_id in ('.', '..') or '\\' in run_id:
            raise ValueError('无效记录目录')
        from .result_paths import relative_run
        relative = relative_run(result.get('relative_directory',run_id))
        if relative.name != run_id: raise ValueError('记录目录与编号不一致')
        destination = Path(target).joinpath(*relative.parts)
        destination.mkdir(parents=True, exist_ok=True)
        with self.client.open_sftp() as sftp:
            for name in result['files']:
                if PurePosixPath(name).name != name or name in ('.', '..') or '\\' in name:
                    raise ValueError('无效结果文件名')
                path = destination / name
                temporary = path.with_name(path.name+'.partial')
                sftp.get(self.remote_root+'/results/'+str(relative)+'/'+name, str(temporary))
                temporary.replace(path)
        # A board-side AC run ends after safe hardware cleanup. Recompute the
        # derived analysis locally on every retrieval, including later fetches.
        # Raw CSV/ADC records remain unchanged.
        if (destination/'run.json').exists():
            from .ac import finish_host_analysis
            finish_host_analysis(destination)
        return destination

    def close(self):
        try:
            return self.call('close', timeout=30)
        finally: self.abort()

    def abort(self):
        self._fail('连接关闭；未收到退出确认时，不能确认输出已停止')
        if self.channel is not None: self.channel.close()
        if self.client is not None: self.client.close()
