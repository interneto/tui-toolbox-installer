"""Redaction of values that came from secret environment variables.

Some AI-agent install commands take credentials from the environment (for
example ``$GRAFANA_SERVICE_ACCOUNT_TOKEN``). Those values have to reach the
argv we execute, but they must never reach the confirmation preview, the run
log or the terminal scrollback.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Variable names that conventionally hold credentials. Matched against the
# whole name, case-insensitively, on a word boundary.
_SECRET_NAME = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|ACCESS[_-]?KEY)",
    re.IGNORECASE,
)


def is_secret_name(name: str) -> bool:
    """True when an environment variable name looks like a credential."""
    return bool(_SECRET_NAME.search(name))


def redact(text: str, values: Iterable[str]) -> str:
    """Replace every secret value in ``text`` with ``***``.

    Longer values are replaced first so a secret that contains another one
    cannot leave a fragment behind.
    """
    for value in sorted((v for v in values if v), key=len, reverse=True):
        text = text.replace(value, "***")
    return text
