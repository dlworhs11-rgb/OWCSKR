"""tools/run_daily.sh git handling, against real git repos in a temp dir. node, python and pgrep are stubs; there is
no systemctl, so env.sh takes its non-systemd paths. Nothing is sent: the python stub only logs its arguments."""
import os, shutil, subprocess

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NODE = r'''#!/usr/bin/env bash
case "$*" in
  *--discover*) [ -n "${FAKE_DISCOVER:-}" ] && printf '%s\n' "$FAKE_DISCOVER" > data/active.json ;;
  *--active-only*) date +%s%N > data/lp/a.json; [ -n "${FAKE_NEW_PAGE:-}" ] && echo fetched > data/lp/new.json ;;
esac
exit 0
'''
PY = '#!/usr/bin/env bash\necho "py $*" >> "$FAKE_LOG"\nexit 0\n'
PGREP = '#!/usr/bin/env bash\nexit "${FAKE_PGREP:-1}"\n'


def _bash():
    b = shutil.which('bash')
    if not b or 'system32' in b.lower():
        pytest.skip('no bash')
    return b


def _script(path, text):
    with open(path, 'w', newline='\n') as f:
        f.write(text)
    os.chmod(path, 0o755)


class World:
    """an upstream repo, a developer clone and the server clone that run_daily.sh runs in"""

    def __init__(self, tmp):
        self.tmp, self.log = tmp, tmp / 'calls.log'
        stubs = tmp / 'stubs'
        stubs.mkdir()
        _script(stubs / 'node', NODE)
        _script(stubs / 'pgrep', PGREP)
        _script(tmp / 'fakepy', PY)
        keep = {k: v for k, v in os.environ.items() if not k.startswith(('OWCSKR_', 'GIT_')) and k != 'GH_TOKEN'}
        self.env = dict(keep, PATH=str(stubs) + os.pathsep + os.environ.get('PATH', ''), HOME=str(tmp),
                        OWCSKR_PYTHON=(tmp / 'fakepy').as_posix(), FAKE_LOG=self.log.as_posix(),
                        GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@x')
        self.git(tmp, 'init', '-q', '--bare', '-b', 'main', 'up.git')
        self.git(tmp, 'clone', '-q', 'up.git', 'dev')
        self.dev, self.srv = tmp / 'dev', tmp / 'srv'
        (self.dev / 'tools').mkdir()
        (self.dev / 'data' / 'lp').mkdir(parents=True)
        for f in ('env.sh', 'run_daily.sh'):
            shutil.copy(os.path.join(HERE, 'tools', f), self.dev / 'tools' / f)
        files = {'.gitattributes': '* -text\n', '.gitignore': 'data/live/\n', 'code.txt': 'v1\n',
                 'data/lp/a.json': 'old\n', 'data/competitions.json': '{}\n', 'data/active.json': '[]\n'}
        for name, text in files.items():
            (self.dev / name).write_text(text, newline='\n')
        self.commit_dev('init')
        self.git(tmp, 'clone', '-q', 'up.git', 'srv')

    def git(self, cwd, *args):
        r = subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=cwd, env=self.env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    def commit_dev(self, msg, **files):
        for name, text in files.items():
            (self.dev / name).write_text(text, newline='\n')
        self.git(self.dev, 'add', '-A')
        self.git(self.dev, 'commit', '-q', '-m', msg)
        self.git(self.dev, 'push', '-q', 'origin', 'main')

    def run_daily(self, **env):
        r = subprocess.run([_bash(), 'tools/run_daily.sh'], cwd=self.srv, env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        daily = (self.srv / 'data' / 'live' / 'daily.log').read_text(encoding='utf-8', errors='replace')
        calls = self.log.read_text(encoding='utf-8') if self.log.exists() else ''
        return r.returncode, daily, calls

    def head(self, ref='HEAD'):
        return self.git(self.srv, 'rev-parse', ref)


@pytest.fixture
def world(tmp_path):
    _bash()
    return World(tmp_path)


def test_job_outputs_do_not_block_the_next_pull(world):
    assert world.run_daily()[0] == 0                    # day 1: refreshes data/lp/a.json (tracked) -> dirty tree
    assert world.git(world.srv, 'status', '--porcelain', '--untracked-files=no')
    world.commit_dev('code', **{'code.txt': 'v2\n'})
    rc, daily, calls = world.run_daily()
    assert rc == 0, daily
    assert (world.srv / 'code.txt').read_text() == 'v2\n'      # the server got the new code
    assert 'restarting with the new code' in daily
    assert 'notify' not in calls


def test_incoming_commit_to_a_job_output_resets_it_and_pulls(world):
    world.run_daily(FAKE_NEW_PAGE='1')                 # data/lp/a.json changed, data/lp/new.json untracked
    world.commit_dev('regen data/lp', **{'data/lp/a.json': 'upstream\n', 'data/lp/new.json': 'upstream\n',
                                         'code.txt': 'v2\n'})
    rc, daily, calls = world.run_daily()
    assert rc == 0, daily
    assert world.head() == world.head('origin/main') and (world.srv / 'code.txt').read_text() == 'v2\n'
    assert 'resetting data/lp' in daily                 # the first pull did refuse
    assert 'notify' not in calls


def test_local_code_change_skips_the_pull_with_a_warning(world):
    (world.srv / 'code.txt').write_text('hand edit\n', newline='\n')
    world.commit_dev('code', **{'code.txt': 'v2\n'})
    rc, daily, calls = world.run_daily()
    assert rc == 0
    assert (world.srv / 'code.txt').read_text() == 'hand edit\n'
    assert 'notify' in calls and 'git pull' in calls      # not silent


def test_no_pull_under_a_running_capture(world):
    world.commit_dev('code', **{'code.txt': 'v2\n'})
    rc, daily, calls = world.run_daily(FAKE_PGREP='0')
    assert rc == 0 and 'capture running - git pull skipped' in daily
    assert (world.srv / 'code.txt').read_text() == 'v1\n'


def test_rejected_push_undoes_the_discovery_commit(world):
    hook = world.tmp / 'up.git' / 'hooks' / 'pre-receive'
    _script(hook, '#!/bin/sh\necho rejected >&2\nexit 1\n')
    rc, daily, calls = world.run_daily(FAKE_DISCOVER='["new"]', OWCSKR_AUTOCOMMIT='1', OWCSKR_AUTOPUSH='1')
    assert rc == 0                                      # a push problem is a warning
    assert 'git push (discover)' in calls
    assert world.head() == world.head('origin/main')    # no local commit left to block tomorrow's pull --ff-only
    assert (world.srv / 'data' / 'active.json').read_text().strip() == '["new"]'   # the change is kept


def test_discovery_commit_is_pushed(world):
    rc, daily, calls = world.run_daily(FAKE_DISCOVER='["new"]', OWCSKR_AUTOCOMMIT='1', OWCSKR_AUTOPUSH='1')
    assert rc == 0, daily
    assert world.head() == world.git(world.dev, 'ls-remote', 'origin', 'main').split()[0]
    assert world.git(world.srv, 'log', '-1', '--format=%s').startswith('data: discovered competitions')


def test_shadow_run_posts_no_replay_comments(world):
    """OWCSKR_PUBLISH=0 (P1-R5): the publishing machine posts the SOOP comments, not this one"""
    site = world.tmp / 'site'
    site.mkdir()
    (site / 'replay_comment.py').write_text('', encoding='utf-8')
    rc, daily, calls = world.run_daily(OWCSKR_SITE_DIR=site.as_posix())
    assert 'replay_comment.py --post' in calls
    world.log.unlink()
    rc, daily, calls = world.run_daily(OWCSKR_SITE_DIR=site.as_posix(), OWCSKR_PUBLISH='0')
    assert 'replay_comment.py' not in calls
    assert 'publish off (OWCSKR_PUBLISH=0) - replay comments not posted' in daily
