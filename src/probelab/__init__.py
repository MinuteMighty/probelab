"""probelab — Find out what your code depends on. Know when it breaks."""

__version__ = "1.0.0-alpha.1"

from probelab.api import check_url, preflight, diagnose_url, CheckResult, DiagnoseResult

__all__ = ["check_url", "preflight", "diagnose_url", "CheckResult", "DiagnoseResult"]
