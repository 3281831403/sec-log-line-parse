"""Stable re-export surface for the parser implementation."""

from logparse._impl import (
    log_batch,
    merge_continuation,
    parse_line,
    parse_timestamp,
    split_fields,
    to_row,
    unescape,
    validate_line,
)

__all__ = [
    "split_fields",
    "unescape",
    "parse_timestamp",
    "to_row",
    "parse_line",
    "validate_line",
    "merge_continuation",
    "log_batch",
]