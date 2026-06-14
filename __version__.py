"""Single source of truth for the OBSCURA version.

Imported by app.py (startup banner + /api/version), cli.py (`obscura version`),
and pyproject.toml (build-time, via dynamic version). Bump this one line to cut
a new release — nothing else hard-codes the version string.
"""
__version__ = "0.4.0.dev0"
