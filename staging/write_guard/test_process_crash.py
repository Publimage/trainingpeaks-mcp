"""Real OS process interruption tests; uses a LOCAL FILE fake provider only."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from guard import DocsWriteGuard, Document, Patch, ReconciliationRequired
from test_guard import FakeAuth


class DiskFakeDocs:
    def __init__(self, state_file):
        self.state_file = Path(state_file)

    def read(self, document_id):
        d = json.loads(self.state_file.read_text())
        return Document(d['revision'], d['text'])

    def replace_once(self, document_id, required_revision, old, new):
        d = json.loads(self.state_file.read_text())
        assert d['revision'] == required_revision
        assert d['text'].count(old) == 1
        d['text'] = d['text'].replace(old, new, 1)
        d['revision'] = 'r2'
        d['writes'] += 1
        tmp = self.state_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(d))
        os.replace(tmp, self.state_file)


PATCH = Patch('op-1', 'doc-1', 'AUTO', 'r1', 'Before block.',
              'Before block. CHECKPOINT-1', 'CHECKPOINT-1', 'approved-scope')


def _worker(state_file, ledger, mode):
    # Entirely local simulation. NO Google or external provider access.
    script = r'''
import os, sys
from test_process_crash import DiskFakeDocs, PATCH
from test_guard import FakeAuth
from guard import DocsWriteGuard
class CrashDocs(DiskFakeDocs):
    def replace_once(self, document_id, required_revision, old, new):
        if sys.argv[3] == 'before':
            os._exit(19)
        super().replace_once(document_id, required_revision, old, new)
        os._exit(20)
DocsWriteGuard(CrashDocs(sys.argv[1]), FakeAuth(), sys.argv[2], {'doc-1'}).execute(PATCH)
'''
    root = Path(__file__).parent
    p = subprocess.run([sys.executable, '-c', script, str(state_file), str(ledger), mode],
                       cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p


@pytest.mark.parametrize('mode,exitcode,writes', [('before', 19, 0), ('after', 20, 1)])
def test_real_process_death_persists_journal_and_recovers_safely(tmp_path, mode, exitcode, writes):
    state_file = tmp_path / 'doc.json'
    state_file.write_text(json.dumps({'revision':'r1','text':'Before block.\n','writes':0}))
    ledger = tmp_path / 'ledger.sqlite3'
    res = _worker(state_file, ledger, mode)
    assert res.returncode == exitcode, res.stderr
    with sqlite3.connect(ledger) as db:
        assert db.execute('SELECT state FROM operations WHERE operation_id=?', ('op-1',)).fetchone()[0] == 'IN_FLIGHT'
    g = DocsWriteGuard(DiskFakeDocs(state_file), FakeAuth(), str(ledger), {'doc-1'})
    if mode == 'after':
        assert g.execute(PATCH) == 'ALREADY_VERIFIED'
        assert json.loads(state_file.read_text())['writes'] == 1
    else:
        with pytest.raises(ReconciliationRequired):
            g.execute(PATCH)
        assert json.loads(state_file.read_text())['writes'] == 0
