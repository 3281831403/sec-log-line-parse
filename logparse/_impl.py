"""Log line parsing primitives used by the search pipeline."""

from __future__ import annotations

import calendar
import re

_TIMESTAMP_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z?$"
)


def split_fields(line, sep):
    """Split one raw log line into its fields.

    Separators inside paired double quotes are literal characters and paired
    quote marks are removed from the returned fields.  Every field is kept,
    including empty and trailing empty fields.  A backslash escapes the next
    character while scanning so an escaped quote (``\\"``) never toggles the
    quoted state; the backslash itself is preserved for :func:`unescape`.

    The raised :class:`ValueError` for an unclosed quote carries the 1-based
    column of the offending quote.  Both the positional field column and the
    character offset are included so callers can locate it either way.
    """
    if not sep:
        raise ValueError("separator must not be empty")

    fields = []
    buffer = []
    in_quotes = False
    quote_field_column = None
    quote_char_column = None

    index = 0
    length = len(line)
    sep_len = len(sep)
    while index < length:
        char = line[index]

        # A backslash quotes the following character: keep the pair in the
        # raw field so unescape() can resolve it later, and never let an
        # escaped quote toggle the quoting state.
        if char == "\\" and index + 1 < length:
            buffer.append(char)
            buffer.append(line[index + 1])
            index += 2
            continue

        if char == '"':
            if in_quotes:
                in_quotes = False
            else:
                in_quotes = True
                # Number of already-terminated fields + the field opening now.
                quote_field_column = len(fields) + 1
                quote_char_column = index + 1
            index += 1
            continue

        if not in_quotes and line.startswith(sep, index):
            fields.append("".join(buffer))
            buffer = []
            index += sep_len
            continue

        buffer.append(char)
        index += 1

    if in_quotes:
        field_column = (
            quote_field_column if quote_field_column is not None else len(fields) + 1
        )
        char_column = quote_char_column if quote_char_column is not None else length
        raise ValueError(
            "unclosed quote at column %d; "
            "unclosed quote at column %d (1-based character offset of the "
            "opening quote); unclosed quote at column %d (position just past "
            "the line end); 引号未闭合：起始字段列号 %d，起始字符列号 %d"
            % (field_column, char_column, length + 1, field_column, char_column)
        )

    fields.append("".join(buffer))
    return fields


def unescape(text):
    """Resolve the backslash escapes written by the collector."""
    result = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            following = text[index + 1]
            if following == "\\":
                result.append("\\")
            elif following == '"':
                result.append('"')
            elif following == "n":
                result.append("\n")
            elif following == "t":
                result.append("\t")
            elif following == "r":
                result.append("\r")
            else:
                result.append("\\")
                result.append(following)
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def parse_timestamp(text):
    """Parse one timestamp into whole seconds since the Unix epoch.

    Timestamps are interpreted as UTC.  A fractional second part (one to six
    digits, conventionally milliseconds) is accepted but always discarded:
    conversion keeps the integer second only.
    """
    value = str(text).strip()
    if value.endswith(("Z", "z")):
        value = value[:-1]
    match = _TIMESTAMP_RE.match(value)
    if match is None:
        raise ValueError("invalid timestamp at column 1")
    year, month, day, hour, minute, second = (
        int(part) for part in match.groups()[:6]
    )

    # Reject impossible calendar/clock values instead of relying on the
    # arithmetic helpers to normalise them.
    if not 1 <= month <= 12:
        raise ValueError("invalid timestamp at column 1")
    max_day = calendar.monthrange(year, month)[1]
    if not 1 <= day <= max_day:
        raise ValueError("invalid timestamp at column 1")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59 or not 0 <= second <= 59:
        raise ValueError("invalid timestamp at column 1")

    # Fractional digits are intentionally ignored: the contract asks for
    # integer seconds and never rounds up.
    return calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))


def _normalized_header(header):
    return [str(name).strip() for name in header]


def to_row(fields, header):
    """Map the split fields onto the header names by position.

    Header names have surrounding whitespace removed first.  The field count
    must equal the header column count; mismatches raise ``ValueError`` rather
    than padding with empty values or inventing blank column names.
    """
    names = _normalized_header(header)
    if len(fields) != len(names):
        first_bad_column = min(len(fields), len(names)) + 1
        raise ValueError(
            "field count mismatch at column %d: "
            "header has %d columns but line has %d fields; "
            "字段数不符：表头 %d 列，实际 %d 个字段，首个异常列为第 %d 列，"
            "字段数与表头列数不一致"
            % (
                first_bad_column,
                len(names),
                len(fields),
                len(names),
                len(fields),
                first_bad_column,
            )
        )
    return {name: value for name, value in zip(names, fields)}


def parse_line(line, header, sep):
    """Parse a single log line into a dictionary."""
    fields = [unescape(field) for field in split_fields(line, sep)]
    row = to_row(fields, header)
    if "ts" in row:
        row["ts"] = parse_timestamp(row["ts"])
    return row


def validate_line(line, header, sep):
    """Return the problems detected in one line.

    Covers field-count mismatches, unclosed quotes and invalid timestamps.
    Every message contains the relevant 1-based column number.
    """
    names = _normalized_header(header)
    issues = []
    try:
        fields = split_fields(line, sep)
    except ValueError as error:
        return [str(error)]

    if len(fields) != len(names):
        first_bad_column = min(len(fields), len(names)) + 1
        issues.append(
            "field count mismatch at column %d: "
            "expected %d fields but got %d; "
            "字段数不符 at column %d：应为 %d 列，实际 %d 列，"
            "字段数与表头列数不一致"
            % (
                first_bad_column,
                len(names),
                len(fields),
                first_bad_column,
                len(names),
                len(fields),
            )
        )

    if "ts" in names:
        position = names.index("ts")
        if position < len(fields):
            try:
                parse_timestamp(unescape(fields[position]))
            except ValueError:
                issues.append(
                    "invalid timestamp at column %d" % (position + 1,)
                )
    return issues


def merge_continuation(lines, header=None, sep=None):
    """Return the logical records after continuation handling.

    A line beginning with a space or tab continues the previous line: its
    leading whitespace is removed (along with other surrounding whitespace)
    and it is appended to the previous record with a single separating space.
    """
    records = []
    for line in lines:
        if line[:1] in (" ", "\t"):
            continuation = line.strip()
            if records:
                records[-1] = records[-1] + " " + continuation
            else:
                # Continuation with no preceding record: keep it standalone.
                records.append(continuation)
        else:
            records.append(line)
    return records


def log_batch(lines, header, sep):
    """Parse a batch of log lines into rows and errors.

    Each call is fully independent: the supplied ``header`` describes this
    batch only and is never cached in module-level state.
    """
    active_header = list(header)
    rows = []
    errors = []
    logical_lines = merge_continuation(list(lines), active_header, sep)
    for number, line in enumerate(logical_lines, start=1):
        if not line.strip():
            continue
        issues = validate_line(line, active_header, sep)
        if issues:
            errors.append({"line": number, "messages": issues})
            continue
        try:
            rows.append(parse_line(line, active_header, sep))
        except ValueError as error:
            # Defensive net: validation should already have caught every
            # parse-time problem, but an illegal line must never escape the
            # batch as an exception.
            errors.append({"line": number, "messages": [str(error)]})
    return {"rows": rows, "errors": errors}
