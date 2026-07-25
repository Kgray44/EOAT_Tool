"""Deprecated compatibility entry point for the unified release CLI."""

if __name__ == "__main__":
    raise SystemExit(
        "DEPRECATED ENTRY POINT. Run `python tools/eoat_release.py candidate rehearse --bump patch` "
        "or `python tools/eoat_release.py candidate prepare --bump patch`. "
        "Legacy arguments are intentionally not forwarded."
    )
