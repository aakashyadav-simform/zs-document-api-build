from app.workers.document_worker import build_summary


def test_build_summary_has_word_count_and_excerpt():

    s = build_summary("one two three", 100)
    assert "3 words" in s
    assert "one two three" in s


def test_build_summary_truncates_to_limit():

    s = build_summary("x" * 1000, 10)
    assert "x" * 10 in s
    assert "x" * 11 not in s
