from guardrails import classify_readiness
from sessions import Session


def test_classify_readiness_no_session():
    assert classify_readiness(None) == "not_connected"


def test_classify_readiness_empty_source():
    sess = Session(session_id="sess_1", record_count=0)
    assert classify_readiness(sess) == "no_source_data"


def test_classify_readiness_negative_treated_as_empty():
    sess = Session(session_id="sess_1", record_count=-1)
    assert classify_readiness(sess) == "no_source_data"


def test_classify_readiness_ready():
    sess = Session(session_id="sess_1", record_count=42)
    assert classify_readiness(sess) == "ready"
