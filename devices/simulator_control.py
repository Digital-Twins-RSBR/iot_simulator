import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings


RUNTIME_DIR = Path(settings.BASE_DIR) / 'runtime'
PID_FILE = RUNTIME_DIR / 'send_telemetry.pid'
LOG_FILE = RUNTIME_DIR / 'send_telemetry.log'


def _ensure_runtime_dir():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _list_simulator_processes():
    processes = []
    proc_root = Path('/proc')
    if not proc_root.exists():
        return processes

    current_pid = os.getpid()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == current_pid:
            continue
        try:
            cmdline = (entry / 'cmdline').read_bytes().replace(b'\x00', b' ').decode('utf-8', errors='ignore').strip()
        except OSError:
            continue

        if 'manage.py' in cmdline and 'send_telemetry' in cmdline:
            processes.append({'pid': pid, 'cmdline': cmdline})
    return processes


def _read_managed_pid():
    try:
        return int(PID_FILE.read_text(encoding='utf-8').strip())
    except (FileNotFoundError, ValueError):
        return None


def _pid_is_running(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_recent_logs(limit=80):
    try:
        lines = LOG_FILE.read_text(encoding='utf-8', errors='ignore').splitlines()
    except FileNotFoundError:
        return []
    return lines[-limit:]


def get_runtime_status():
    managed_pid = _read_managed_pid()
    external_processes = _list_simulator_processes()
    managed_running = _pid_is_running(managed_pid)

    if managed_pid and not managed_running and PID_FILE.exists():
        PID_FILE.unlink(missing_ok=True)
        managed_pid = None

    active_pid = managed_pid if managed_running else (external_processes[0]['pid'] if external_processes else None)
    mode = 'managed' if managed_running else ('external' if external_processes else 'stopped')
    return {
        'is_running': bool(managed_running or external_processes),
        'mode': mode,
        'managed_pid': managed_pid if managed_running else None,
        'active_pid': active_pid,
        'processes': external_processes,
        'log_path': str(LOG_FILE),
        'pid_path': str(PID_FILE),
        'updated_at': int(time.time()),
    }


def start_simulator(randomize=True, use_memory=True, use_influxdb=False, system=None, device_type=None):
    status = get_runtime_status()
    if status['is_running']:
        return {'ok': False, 'message': 'Simulator already running.', 'runtime': status}

    _ensure_runtime_dir()
    command = [sys.executable, 'manage.py', 'send_telemetry']
    if use_influxdb:
        command.append('--use-influxdb')
    if randomize:
        command.append('--randomize')
    if use_memory:
        command.append('--memory')
    if system:
        command.extend(['--system', system])
    if device_type:
        command.extend(['--device-type', device_type])

    log_handle = LOG_FILE.open('a', encoding='utf-8')
    env = os.environ.copy()
    env.setdefault('DJANGO_SETTINGS_MODULE', 'iot_simulator.settings_base')
    process = subprocess.Popen(
        command,
        cwd=settings.BASE_DIR,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    PID_FILE.write_text(str(process.pid), encoding='utf-8')
    return {
        'ok': True,
        'message': 'Simulator started.',
        'runtime': get_runtime_status(),
    }


def stop_simulator():
    managed_pid = _read_managed_pid()
    killed = []

    if managed_pid and _pid_is_running(managed_pid):
        try:
            # try to terminate the process group first (works if started with start_new_session)
            os.killpg(managed_pid, signal.SIGTERM)
        except OSError:
            pass
        killed.append(managed_pid)

    for process in _list_simulator_processes():
        pid = process['pid']
        if pid in killed:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except OSError:
            continue
    # wait briefly for processes to exit; escalate to SIGKILL if still present
    timeout = 4
    start = time.time()
    while time.time() - start < timeout:
        remaining = [p for p in killed if _pid_is_running(p)]
        if not remaining:
            break
        time.sleep(0.2)

    for p in [p for p in killed if _pid_is_running(p)]:
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            continue

    PID_FILE.unlink(missing_ok=True)
    return {
        'ok': bool(killed),
        'message': 'Simulator stopped.' if killed else 'No simulator process found.',
        'killed_pids': killed,
        'runtime': get_runtime_status(),
    }