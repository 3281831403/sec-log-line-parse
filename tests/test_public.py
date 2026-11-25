"""Public behaviour checks for the log line parser."""

from logparse import log_batch, parse_line, parse_timestamp, to_row


def test_parse_two_fields():
    row = parse_line('alice,"a,b"', ["name", "tag"], ",")
    assert row == {"name": "alice", "tag": "a,b"}


def test_timestamp_parses():
    assert parse_timestamp("2024-01-02T03:04:05.250Z") == 1704164645


def test_header_mapping_returns_dict():
    row = to_row(["alice", "30"], [" name ", "age "])
    assert row == {"name": "alice", "age": "30"}


def test_blank_lines_are_skipped():
    result = log_batch(["", "alice\t30", "broken"], ["name", "age"], "\t")
    assert len(result["rows"]) == 1
    assert len(result["errors"]) == 1


def test_two_batches_are_independent():
    first = log_batch(["alice\t30"], ["name", "age"], "\t")
    second = log_batch(["bob\t25"], ["user", "score"], "\t")
    assert first == {"rows": [{"name": "alice", "age": "30"}], "errors": []}
    assert second == {"rows": [{"user": "bob", "score": "25"}], "errors": []}