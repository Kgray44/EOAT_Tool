"""Deprecated compatibility entry point for the unified deployment CLI."""

if __name__ == "__main__":
    raise SystemExit(
        "DEPRECATED ENTRY POINT. Run `python tools/eoat_release.py target inspect --server-config <path>` "
        "or `python tools/eoat_release.py releases list`. Legacy arguments are intentionally not forwarded."
    )
