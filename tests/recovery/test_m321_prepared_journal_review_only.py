"""Offline-only tests: no SQL, Docker, database driver, or worker imports."""
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4
import pytest

SOURCE = Path(__file__).resolve().parents[2] / 'tools/recovery/m321_prepared_journal_review_only.py'
OFFLINE_TEMP_ROOT = Path(
    os.environ.get('HAD_OFFLINE_TEST_TMP', tempfile.gettempdir())
) / 'healthcare-ai-desk-pytest'
spec=importlib.util.spec_from_file_location('m321_prepared_review_only', SOURCE)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def evidence(ok=True):
    return [{'check':'offline', 'expected':True, 'observed':ok, 'passed':ok}]


@pytest.fixture
def workspace_tmp():
    """Use an explicit local-only root and skip cleanly when it is unavailable.

    Set ``HAD_OFFLINE_TEST_TMP`` to a writable directory on Windows when the
    default user TEMP policy is restricted. This never selects a database or
    infrastructure path.
    """
    try:
        OFFLINE_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        probe = OFFLINE_TEMP_ROOT / '.write-probe'
        probe.write_bytes(b'')
        probe.unlink()
    except OSError as exc:
        pytest.skip(
            'offline local-file journal tests require a writable temp root; '
            'set HAD_OFFLINE_TEST_TMP to a user-writable local directory '
            f'(current root: {OFFLINE_TEMP_ROOT}; {exc.__class__.__name__})'
        )
    prefix = OFFLINE_TEMP_ROOT / f'prepared-journal-{uuid4().hex}'
    try:
        yield prefix
    finally:
        # The sandbox can deny child-directory cleanup. These are flat,
        # test-owned files beneath the explicit local temp root, not directories.
        for artifact in OFFLINE_TEMP_ROOT.glob(f'{prefix.name}-*'):
            try:
                artifact.unlink()
            except OSError:
                pass


def make(tmp_prefix):
    pre=Path(f'{tmp_prefix}-before.json'); pre.write_text('{"schema": "before"}')
    post=Path(f'{tmp_prefix}-after.json'); post.write_text('{"schema": "after"}')
    path=Path(f'{tmp_prefix}-journal.json')
    return path,pre,post


def store(path):
    return mod.PreparedReviewStore(path, rehearsal_id='offline-uuid', reviewed_sql_sha256='a'*64)


def test_prepared_persisted_before_result(workspace_tmp):
    path,pre,post=make(workspace_tmp)
    with store(path) as j:
        j.prepare(step_id='s1', statement='SELECT 1', observed_preconditions=evidence(), before_snapshot=pre)
        assert json.loads(path.read_text())['status']=='PREPARED'
        j.record_pass(step_id='s1', observed_postconditions=evidence(), after_snapshot=post)
        assert j.snapshot['status']=='READY_REVIEW_ONLY'
    with store(path) as j:
        assert j.snapshot['events'][-1]['type']=='PASSED'


def test_restart_unresolved_prepared_fails_closed(workspace_tmp):
    path,pre,_=make(workspace_tmp)
    with store(path) as j:
        j.prepare(step_id='s1', statement='SELECT 1', observed_preconditions=evidence(), before_snapshot=pre)
    with pytest.raises(mod.ReviewJournalError, match='no resume'):
        with store(path):
            pass


def test_terminal_no_retry_persists(workspace_tmp):
    path,pre,post=make(workspace_tmp)
    with store(path) as j:
        j.prepare(step_id='s1', statement='SELECT 1', observed_preconditions=evidence(), before_snapshot=pre)
        j.stop_no_retry(step_id='s1', reason_code='FAILED', exit_code=2, observed_postconditions=evidence(False), after_snapshot=post)
        with pytest.raises(mod.ReviewJournalError):
            j.prepare(step_id='s2',statement='SELECT 2',observed_preconditions=evidence(),before_snapshot=pre)
    with pytest.raises(mod.ReviewJournalError, match='no resume'):
        with store(path): pass


def test_exclusive_writer_refuses_concurrent_open(workspace_tmp):
    path,_,_=make(workspace_tmp)
    with store(path):
        with pytest.raises(mod.ReviewJournalError, match='Exclusive journal writer lock unavailable'):
            with store(path): pass


def test_failed_observation_prevents_prepared(workspace_tmp):
    path,pre,_=make(workspace_tmp)
    with store(path) as j:
        with pytest.raises(mod.ReviewJournalError, match='Failed assertion'):
            j.prepare(step_id='s1',statement='SELECT 1',observed_preconditions=evidence(False),before_snapshot=pre)
        assert j.snapshot['status']=='PENDING_REVIEW'


def test_failed_postcondition_cannot_pass(workspace_tmp):
    path,pre,post=make(workspace_tmp)
    with store(path) as j:
        j.prepare(step_id='s1',statement='SELECT 1',observed_preconditions=evidence(),before_snapshot=pre)
        with pytest.raises(mod.ReviewJournalError,match='Failed assertion'):
            j.record_pass(step_id='s1', observed_postconditions=evidence(False),after_snapshot=post)
        assert j.snapshot['status']=='PREPARED'


def test_snapshot_hash_matches_actual_content(workspace_tmp):
    path,pre,post=make(workspace_tmp)
    with store(path) as j:
        j.prepare(step_id='s1',statement='SELECT 1',observed_preconditions=evidence(),before_snapshot=pre)
        j.record_pass(step_id='s1',observed_postconditions=evidence(),after_snapshot=post)
        assert j.snapshot['events'][1]['after_snapshot_sha256']==mod._digest_file(post)


def test_tamper_detected(workspace_tmp):
    path,_,_=make(workspace_tmp)
    with store(path): pass
    data=json.loads(path.read_text());data['status']='PREPARED';path.write_text(json.dumps(data))
    with pytest.raises(mod.ReviewJournalError,match='integrity mismatch'):
        with store(path): pass


def test_changed_snapshot_refuses_reload(workspace_tmp):
    path, pre, post = make(workspace_tmp)
    with store(path) as j:
        j.prepare(step_id='s1', statement='SELECT 1', observed_preconditions=evidence(), before_snapshot=pre)
        j.record_pass(step_id='s1', observed_postconditions=evidence(), after_snapshot=post)
    post.write_text('altered snapshot content')
    with pytest.raises(mod.ReviewJournalError, match='After-snapshot evidence mismatched'):
        with store(path): pass


def test_existing_stale_lock_refuses_open(workspace_tmp):
    path, _, _ = make(workspace_tmp)
    lock = Path(str(path) + '.lock')
    lock.write_text('unknown previous owner')
    with pytest.raises(mod.ReviewJournalError, match='Exclusive journal writer lock unavailable'):
        with store(path): pass
    assert lock.read_text() == 'unknown previous owner'
