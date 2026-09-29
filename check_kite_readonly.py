"""Read-only Kite API capability check.

Run from the project root:
    .venv/bin/python check_kite_readonly.py

This script does not place, modify, or cancel orders. It only checks whether the
current saved Kite token can read profile, funds, quotes, orders, and positions.
"""
from __future__ import annotations

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

from app.core.config import settings
from app.core.zerodha_auth import zerodha_auth


def check(name: str, fn) -> None:
    try:
        value = fn()
        if isinstance(value, dict):
            print(f"{name}: OK keys={list(value.keys())[:8]}")
        elif isinstance(value, list):
            print(f"{name}: OK count={len(value)}")
        else:
            print(f"{name}: OK {type(value).__name__}")
    except Exception as exc:
        print(f"{name}: FAIL {type(exc).__name__}: {exc}")


def main() -> None:
    try:
        zerodha_auth._load_token()
        kite = zerodha_auth.get_kite_instance()
    except Exception as exc:
        print(f"AUTH_INIT: FAIL {type(exc).__name__}: {exc}")
        return

    print("READ_ONLY_CHECK: no orders will be placed")
    print("API_KEY_SUFFIX:", (settings.KITE_API_KEY or "")[-4:])
    print("REDIRECT_URL:", settings.KITE_REDIRECT_URL)
    print("LIVE_TRADING_FLAG:", settings.ENABLE_LIVE_TRADING)

    check("PROFILE", lambda: kite.profile())
    check("MARGINS_EQUITY", lambda: kite.margins(segment="equity"))
    check("LTP_INFY", lambda: kite.ltp(["NSE:INFY"]))
    check("QUOTE_INFY", lambda: kite.quote(["NSE:INFY"]))
    check("ORDERS_READ", lambda: kite.orders())
    check("POSITIONS_READ", lambda: kite.positions())


if __name__ == "__main__":
    main()
