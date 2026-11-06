import os

import pandas as pd
import pytest

from main import MarketDataService, _compute_indicator_summary, get_forex_signal, get_market_status


def test_market_status_without_credentials_is_disconnected(monkeypatch):
    for key in [
        "UPSTOX_API_KEY",
        "UPSTOX_CLIENT_CODE",
        "UPSTOX_ACCESS_TOKEN",
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
        "OANDA_API_KEY",
        "OANDA_ACCOUNT_ID",
    ]:
        monkeypatch.delenv(key, raising=False)

    status = get_market_status()
    assert status["status"] == "DEGRADED"
    assert status["markets"]["India"]["status"] == "DISCONNECTED"
    assert status["markets"]["United States"]["status"] == "DISCONNECTED"
    assert status["markets"]["Forex"]["status"] == "DISCONNECTED"


def test_market_status_uses_verified_live_provider(monkeypatch):
    monkeypatch.setenv("UPSTOX_API_KEY", "demo-key")
    monkeypatch.setenv("UPSTOX_CLIENT_CODE", "demo-client")
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "demo-token")
    monkeypatch.setenv("ALPACA_API_KEY", "demo-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "demo-secret")
    monkeypatch.setenv("OANDA_API_KEY", "demo-key")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "demo-account")

    monkeypatch.setattr("main._verify_market_provider", lambda market: {"status": "LIVE", "provider": "demo", "checked_at": "2026-11-03T00:00:00Z"})

    status = get_market_status()
    assert status["markets"]["India"]["status"] == "LIVE"
    assert status["markets"]["United States"]["status"] == "LIVE"
    assert status["markets"]["Forex"]["status"] == "LIVE"
    assert status["status"] == "LIVE"


def test_symbol_normalization_handles_lowercase_and_hyphenated_pairs(monkeypatch):
    import main

    monkeypatch.setattr("main._get_quote_for_symbol", lambda symbol: {"symbol": symbol, "price": 1.0, "market_data_status": "HISTORICAL", "provider": "Yahoo Finance"})

    assert main._normalize_symbol(" aapl ") == "AAPL"
    assert main._normalize_symbol("eur-usd") == "EUR/USD"

    service = MarketDataService()
    service.register_subscription("United States", "aapl")
    snapshot = service.market_snapshot("aapl")
    assert snapshot["symbol"] == "AAPL"


def test_env_aliases_are_applied(monkeypatch):
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    monkeypatch.setenv("ALPACA_SECRET_KEY", "alias-secret")
    import main

    main._apply_env_aliases()
    assert os.environ["ALPACA_API_SECRET"] == "alias-secret"


def test_invalid_fx_pair_rejected(monkeypatch):
    monkeypatch.setenv("UPSTOX_API_KEY", "demo-key")
    monkeypatch.setenv("UPSTOX_CLIENT_CODE", "demo-client")
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "demo-token")

    with pytest.raises(Exception):
        get_forex_signal("NOT_A_PAIR")


def test_provider_snapshot_and_subscription_tracking():
    service = MarketDataService()
    service.register_subscription("United States", "AAPL")
    snapshot = service.market_snapshot("AAPL")

    assert snapshot["symbol"] == "AAPL"
    assert "provider_status" in snapshot
    assert "market_data_status" in snapshot
    assert service.reconnect_delay("United States") >= 1


def test_indicator_summary_computes_numeric_series():
    df = pd.DataFrame(
        {
            "open": [100.0, 101.5, 102.0, 101.2, 103.5],
            "high": [102.0, 103.2, 103.8, 103.1, 104.8],
            "low": [99.0, 100.4, 100.8, 99.9, 101.1],
            "close": [101.0, 102.3, 101.5, 102.8, 103.9],
            "volume": [1000, 1200, 1100, 900, 1400],
        }
    )
    summary = _compute_indicator_summary(df)

    assert "SMA" in summary
    assert "EMA" in summary
    assert "RSI" in summary
    assert "Heikin-Ashi" in summary
    assert len(summary["SMA"]) == len(df)
    assert all(isinstance(value, float) for value in summary["RSI"])
