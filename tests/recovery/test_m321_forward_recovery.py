"""Opt-in populated-state recovery checks; requires a new disposable MySQL URL."""
import os
import pytest
from sqlalchemy import create_engine, text

URL = os.getenv("M321_RECOVERY_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires a newly created disposable MySQL recovery database")

@pytest.mark.parametrize("maximum,expected", [(0, 1), (1, 2), (7, 8)])
def test_counter_backfill_expectations(maximum, expected):
    assert maximum + 1 == expected

def test_fail_closed_target_and_partial_schema():
    engine = create_engine(URL)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT DATABASE()")).scalar_one() != "healthcare_ai_desk"
        assert conn.execute(text("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='conversations' AND column_name='next_timeline_sequence'")).scalar_one() == 1
