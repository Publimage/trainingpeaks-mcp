"""Local command-boundary tests. No remote host or real deployment is used."""
from pathlib import Path
import json
import os
import subprocess
import sys

SCRIPT = Path('scripts/ironman_jobs/deploy_coaching_radar_v2_detached_20261017.sh')
SHA = 'a' * 40


def _executable(path, body):
    path.write_text(f'#!{sys.executable}\n' + body, encoding='utf-8')
    path.chmod(0o755)


def _sandbox(tmp_path):
    repo = tmp_path / 'repo'
    home = tmp_path / 'service-home'
    commands = tmp_path / 'bin'
    for directory in (repo, home, commands):
        directory.mkdir()
    trace = tmp_path / 'trace.jsonl'
    env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH'],
               TEST_REPO=str(repo), TEST_HOME=str(home), TEST_TRACE=str(trace),
               TEST_BIN=str(commands), TEST_SHA=SHA, HOME=str(tmp_path))
    _executable(commands / 'hostname', "print('ironman-prefect-staging')\n")
    _executable(commands / 'getent', "import os\nprint('ironmanprefect:x:1001:1001::' + os.environ['TEST_HOME'] + ':/bin/bash')\n")
    _executable(commands / 'systemctl', "import os,sys\nif sys.argv[1] == 'show': print(os.environ['TEST_BIN'] + '/prefect')\n")
    _executable(commands / 'runuser', "import subprocess,sys\nassert sys.argv[1:4] == ['-u','ironmanprefect','--']\nsys.exit(subprocess.run(sys.argv[4:]).returncode)\n")
    _executable(commands / 'git', "import os,sys\nassert os.environ['HOME'] == os.environ['TEST_HOME']\nassert sys.argv[1:3] == ['-C',os.environ['TEST_REPO']]\nif sys.argv[3] == 'rev-parse': print(os.environ['TEST_SHA'])\n")
    common = "import os,sys,json\nassert os.getcwd() == os.environ['TEST_REPO']\nassert os.environ['HOME'] == os.environ['TEST_HOME']\nassert os.environ['PREFECT_API_URL'] == 'http://127.0.0.1:4200/api'\nwith open(os.environ['TEST_TRACE'],'a') as f: f.write(json.dumps(sys.argv) + '\\n')\n"
    _executable(commands / 'prefect', common)
    _executable(commands / 'python', common)
    local = tmp_path / 'deploy.sh'
    local.write_text(SCRIPT.read_text().replace('REPO=/opt/ironman-prefect/radar-src', 'REPO=' + str(repo))
                     .replace('LOG=/var/log/ironman-radar-v2-deploy.log', 'LOG=' + str(tmp_path / 'deploy.log')))
    return local, env, trace


def test_shell_syntax():
    subprocess.run(['bash', '-n', str(SCRIPT)], check=True)


def test_detached_deploy_sets_cwd_and_service_home(tmp_path):
    local, env, trace = _sandbox(tmp_path)
    subprocess.run(['bash', str(local), SHA, '2026-10-17'], cwd=tmp_path, env=env, check=True)
    calls = [json.loads(x) for x in trace.read_text().splitlines()]
    assert len(calls) == 3
    assert calls[0][-2:] == ['--name', 'polverari-readonly-daily-v2']
    assert calls[1][-2:] == ['--name', 'alberto-group-readonly-daily']
    assert calls[2][-2:] == ['--as-of', '2026-10-17']
    assert 'RADAR_V2_DETACHED_DEPLOY_PASS' in (tmp_path / 'deploy.log').read_text()


def test_bad_revision_does_not_deploy(tmp_path):
    local, env, trace = _sandbox(tmp_path)
    result = subprocess.run(['bash', str(local), 'invalid', '2026-10-17'], cwd=tmp_path, env=env)
    assert result.returncode == 2
    assert not trace.exists()


def test_revision_mismatch_does_not_deploy(tmp_path):
    local, env, trace = _sandbox(tmp_path)
    env['TEST_SHA'] = 'b' * 40
    result = subprocess.run(['bash', str(local), SHA, '2026-10-17'], cwd=tmp_path, env=env)
    assert result.returncode == 4
    assert not trace.exists()
