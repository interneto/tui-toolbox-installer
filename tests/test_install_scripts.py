"""The one-liner bootstraps install a fixed release, never a moving branch."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    # tomllib is 3.11+, and the suite also runs on 3.10.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version = "([^"]+)"$', text, re.M).group(1)


def test_install_sh_pins_the_project_version():
    script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert re.search(r'^VERSION="([^"]+)"$', script, re.M).group(1) == _project_version()
    assert 'REF="${INTERNETO_REF:-v$VERSION}"' in script
    assert 'tui-toolbox-installer@$REF"' in script


def test_install_ps1_pins_the_project_version():
    script = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    assert re.search(r"^\$Version = '([^']+)'$", script, re.M).group(1) == _project_version()
    assert "$Ref = if ($env:INTERNETO_REF) { $env:INTERNETO_REF } else { \"v$Version\" }" in script
    assert "tui-toolbox-installer@$Ref" in script
