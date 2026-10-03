"""Allowlisted database error descriptions: never echo driver connection text."""
import re


def safe_error(error, stage):
    message = str(error).lower()
    reasons = (
        (r"connection is lost|connection is closed", "connection lost or closed"),
        (r"server closed the connection unexpectedly|consuming input failed", "server connection closed unexpectedly"),
        (r"canceling statement due to lock timeout", "lock timeout"),
        (r"canceling statement due to statement timeout", "statement timeout"),
        (r"deadlock detected", "deadlock detected"),
        (r"relation[^\n]*does not exist", "relation does not exist (check transaction schema)"),
        (r"unsupported startup parameter[^\n]*search_path", "unsupported startup parameter: search_path"),
        (r"unsupported startup parameter[^\n]*options", "unsupported startup parameter: options"),
        (r"permission denied[^\n]*schema", "permission denied for schema"),
        (r"permission denied[^\n]*database", "permission denied for database"),
        (r"permission denied", "permission denied"),
        (r"timeout expired|connection timeout|timed out", "connection or statement timeout"),
        (r"password authentication failed", "authentication failed"),
        (r"ssl|tls", "TLS connection error"),
        (r"could not translate host name|name or service not known|nodename nor servname", "hostname resolution failed"),
        (r"connection refused", "connection refused"),
        (r"schema[^\n]*does not exist", "schema does not exist"),
        (r"invalid value for parameter", "invalid configuration parameter value"),
    )
    reason = next((label for pattern, label in reasons if re.search(pattern, message)),
                  "driver error; raw connection details suppressed")
    state = getattr(error, "sqlstate", None)
    state = state if isinstance(state, str) and re.fullmatch(r"[A-Z0-9]{5}", state) else "unavailable"
    # Class names are driver types, not user/database input.
    return f"{stage}: {type(error).__name__}; SQLSTATE={state}; {reason}"


def connection_state(connection):
    if connection is None:
        return "closed=unavailable; status=unavailable; transaction=unavailable"
    return (f"closed={bool(connection.closed)}; "
            f"status={connection.info.status.name}; "
            f"transaction={connection.info.transaction_status.name}")
