"""Offline-only tests: no SQL, Docker, database driver, or worker imports."""
import importlib.util
import json
from pathlib import Path
import pytest

SOURCE = Path(__file__).resolve().parents[2] / 'tools/recovery/m321_prepared_journal_review_only.py'
spec=importlib.util.spec_from_file_location('m321_prepared_review_only', SOURCE)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def evidence(ok=True):
    return [{'check':'offline', 'expected':True, 'observed':ok, 'passed':ok}]


def make(tmp_path):
    pre=tmp_path/'before.json'; pre.write_text('{"schema": "before"}')
    post=tmp_path/'after.json'; post.write_text('{"schema": "after"}')
    path=tmp_path/'journal.json'
    return path,pre,post


def store(path):
    return mod.PreparedReviewStore(path, rehearsal_id='offline-uuid', reviewed_sql_sha256='a'*64)


def test_prepared_persisted_before_result(tmp_path):
    path,pre,post=make(tmp_path)
    with store(path) as j:
        j.prepare(step_id='s1', statement='SELECT 1', observed_preconditions=evidence(), before_snapshot=pre)
        assert json.loads(path.read_text())['status']=='PREPARED'
        j.record_pass(step_id='s1', observed_postconditions=evidence(), after_snapshot=post)
        assert j.snapshot['status']=='READY_REVIEW_ONLY'
    with store(path) as j:
        assert j.snapshot['events'][-1]['type']=='PASSED'


def test_restart_unresolved_prepared_fails_closed(tmp_path):
    path,pre,_=make(tmp_path)
    with store(path) as j:
        j.prepare(step_id='s1', statement='SELECT 1', observed_preconditions=evidence(), before_snapshot=pre)
    with pytest.raises(mod.ReviewJournalError, match='no resume'):
        with store(path):
            pass


def test_terminal_no_retry_persists(tmp_path):
    path,pre,post=make(tmp_path)
    with store(path) as j:
        j.prepare(step_id='s1', statement='SELECT 1', observed_preconditions=evidence(), before_snapshot=pre)
        j.stop_no_retry(step_id='s1', reason_code='FAILED', exit_code=2, observed_postconditions=evidence(False), after_snapshot=post)
        with pytest.raises(mod.ReviewJournalError):
            j.prepare(step_id='s2',statement='SELECT 2',observed_preconditions=evidence(),before_snapshot=pre)
    with pytest.raises(mod.ReviewJournalError, match='no resume'):
        with store(path): pass


def test_exclusive_writer_refuses_concurrent_open(tmp_path):
    path,_,_=make(tmp_path)
    with store(path):
        with pytest.raises(mod.ReviewJournalError, match='Exclusive journal writer lock unavailable'):
            with store(path): pass


def test_failed_observation_prevents_prepared(tmp_path):
    path,pre,_=make(tmp_path)
    with store(path) as j:
        with pytest.raises(mod.ReviewJournalError, match='Failed assertion'):
            j.prepare(step_id='s1',statement='SELECT 1',observed_preconditions=evidence(False),before_snapshot=pre)
        assert j.snapshot['status']=='PENDING_REVIEW'


def test_failed_postcondition_cannot_pass(tmp_path):
    path,pre,post=make(tmp_path)
    with store(path) as j:
        j.prepare(step_id='s1',statement='SELECT 1',observed_preconditions=evidence(),before_snapshot=pre)
        with pytest.raises(mod.ReviewJournalError,match='Failed assertion'):
            j.record_pass(step_id='s1', observed_postconditions=evidence(False),after_snapshot=post)
        assert j.snapshot['status']=='PREPARED'


def test_snapshot_hash_matches_actual_content(tmp_path):
    path,pre,post=make(tmp_path)
    with store(path) as j:
        j.prepare(step_id='s1',statement='SELECT 1',observed_preconditions=evidence(),before_snapshot=pre)
        j.record_pass(step_id='s1',observed_postconditions=evidence(),after_snapshot=post)
        assert j.snapshot['events'][1]['after_snapshot_sha256']==mod._digest_file(post)


def test_tamper_detected(tmp_path):
    path,_,_=make(tmp_path)
    with store(path): pass
    data=json.loads(path.read_text());data['status']='PREPARED';path.write_text(json.dumps(data))
    with pytest.raises(mod.ReviewJournalError,match='integrity mismatch'):
        with store(path): pass


def test_changed_snapshot_refuses_reload(tmp_path):
    path, pre, post = make(tmp_path)
    with store(path) as j:
        j.prepare(step_id='s1', statement='SELECT 1', observed_preconditions=evidence(), before_snapshot=pre)
        j.record_pass(step_id='s1', observed_postconditions=evidence(), after_snapshot=post)
    post.write_text('altered snapshot content')
    with pytest.raises(mod.ReviewJournalError, match='After-snapshot evidence mismatched'):
        with store(path): pass


def test_existing_stale_lock_refuses_open(tmp_path):
    path, _, _ = make(tmp_path)
    lock = Path(str(path) + '.lock')
    lock.write_text('unknown previous owner')
    with pytest.raises(mod.ReviewJournalError, match='Exclusive journal writer lock unavailable'):
        with store(path): pass
    assert lock.read_text() == 'unknown previous owner'
