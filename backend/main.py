from __future__ import annotations

import asyncio
import json
import math
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from urllib import request
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import uvicorn
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"


def _load_env_file() -> None:
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _apply_env_aliases() -> None:
    aliases = {
        "UPSTOX_API_KEY": ("UPSTOX_API_KEY", "UPSTOX_KEY"),
        "UPSTOX_CLIENT_CODE": ("UPSTOX_CLIENT_CODE", "UPSTOX_CLIENT_ID", "UPSTOX_CLIENTID"),
        "UPSTOX_ACCESS_TOKEN": ("UPSTOX_ACCESS_TOKEN", "UPSTOX_TOKEN", "UPSTOX_API_TOKEN"),
        "ALPACA_API_KEY": ("ALPACA_API_KEY", "APCA_API_KEY_ID", "ALPACA_KEY_ID"),
        "ALPACA_API_SECRET": ("ALPACA_API_SECRET", "ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY"),
        "OANDA_API_KEY": ("OANDA_API_KEY", "OANDA_KEY"),
        "OANDA_ACCOUNT_ID": ("OANDA_ACCOUNT_ID", "OANDA_ACCOUNT_NUMBER", "OANDA_ACCOUNT"),
    }
    for canonical, candidates in aliases.items():
        if os.environ.get(canonical):
            continue
        for name in candidates[1:]:
            if os.environ.get(name):
                os.environ[canonical] = os.environ[name]
                break


_load_env_file()
_apply_env_aliases()

app = FastAPI(
    title="QUANT-X API",
    description="Global algorithmic trading and market intelligence platform",
    version="2.1.0",
)

MARKET_PROVIDER_REQUIREMENTS = {
    "India": {
        "provider": "Upstox / authorized NSE-BSE market data",
        "status": "DISCONNECTED",
        "requires_subscription": True,
        "required_credentials": ["UPSTOX_API_KEY", "UPSTOX_CLIENT_CODE", "UPSTOX_ACCESS_TOKEN"],
        "notes": "Live NSE/BSE data requires an active authorized vendor subscription and exchange permissions.",
    },
    "United States": {
        "provider": "Alpaca / authorized US market data",
        "status": "DISCONNECTED",
        "requires_subscription": True,
        "required_credentials": ["ALPACA_API_KEY", "ALPACA_API_SECRET"],
        "notes": "Use an approved market-data plan with direct exchange or SIP data access.",
    },
    "Forex": {
        "provider": "OANDA / authorized FX streaming provider",
        "status": "DISCONNECTED",
        "requires_subscription": True,
        "required_credentials": ["OANDA_API_KEY", "OANDA_ACCOUNT_ID"],
        "notes": "A live FX connection requires an active broker/account with streaming access.",
    },
}

PROVIDER_STATUS_VALUES = {"DISCONNECTED", "DELAYED", "AUTHORIZED", "LIVE"}


def _market_name_for_symbol(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized.endswith(".NS") or normalized.startswith("^NSE") or normalized.startswith("^BSE"):
        return "India"
    if "/" in symbol:
        return "Forex"
    return "United States"


class MarketDataService:
    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._subscriptions: Dict[str, set[str]] = {"India": set(), "United States": set(), "Forex": set()}
        self._last_status_at: Dict[str, float] = {}
        self._reconnect_attempts: Dict[str, int] = {}
        self._provider_handlers: Dict[str, Dict[str, Any]] = {
            "India": {
                "provider": "Upstox / authorized NSE-BSE market data",
                "validator": lambda quote: isinstance(quote, dict) and (quote.get("price") is not None or quote.get("close") is not None),
                "fallback": "Yahoo Finance",
            },
            "United States": {
                "provider": "Alpaca / authorized US market data",
                "validator": lambda quote: isinstance(quote, dict) and (quote.get("price") is not None or quote.get("close") is not None),
                "fallback": "Yahoo Finance",
            },
            "Forex": {
                "provider": "OANDA / authorized FX streaming provider",
                "validator": lambda quote: isinstance(quote, dict) and (quote.get("price") is not None or quote.get("ask") is not None),
                "fallback": "Yahoo Finance",
            },
        }

    def _refresh_cache(self, key: str, value: Dict[str, Any]) -> Dict[str, Any]:
        self._cache[key] = {**value, "cached_at": time.time()}
        return self._cache[key]

    def _active_quote(self, symbol: str) -> Dict[str, Any] | None:
        normalized_symbol = _normalize_symbol(symbol)
        cached = self._cache.get(normalized_symbol)
        if cached is not None:
            return cached
        quote = _get_quote_for_symbol(normalized_symbol)
        if quote is None:
            return None
        if not self._provider_handlers.get(_market_name_for_symbol(normalized_symbol), {}).get("validator", lambda _: True)(quote):
            return None
        quote["market_data_status"] = quote.get("market_data_status", "HISTORICAL")
        self._cache[normalized_symbol] = quote
        return quote

    def get_provider_status(self, market_name: str) -> Dict[str, Any]:
        details = MARKET_PROVIDER_REQUIREMENTS[market_name]
        credentials_present = sum(1 for key in details["required_credentials"] if os.getenv(key))
        verification = _verify_market_provider(market_name)
        if not credentials_present:
            status = "DISCONNECTED"
        elif verification and verification.get("status") == "LIVE":
            status = "LIVE"
        elif verification and verification.get("status") == "AUTHORIZED":
            status = "AUTHORIZED"
        elif credentials_present > 0:
            status = "DELAYED"
        else:
            status = "DISCONNECTED"
        payload = {
            "provider": verification.get("provider", details["provider"]) if verification else details["provider"],
            "status": status,
            "requires_subscription": details["requires_subscription"],
            "required_credentials": details["required_credentials"],
            "notes": details["notes"],
            "credentials_present": credentials_present,
            "timestamp": _now_iso(),
        }
        self._last_status_at[market_name] = time.time()
        return payload

    def get_market_status(self) -> Dict[str, Any]:
        provider_status = {market_name: self.get_provider_status(market_name) for market_name in MARKET_PROVIDER_REQUIREMENTS}
        overall_status = "LIVE" if all(item["status"] == "LIVE" for item in provider_status.values()) else "DEGRADED"
        return {
            "status": overall_status,
            "markets": provider_status,
            "warning": "Historical market data is available without credentials; live labels require verified provider connectivity.",
            "timestamp": _now_iso(),
        }

    def register_subscription(self, market_name: str, symbol: str) -> None:
        normalized_symbol = _normalize_symbol(symbol)
        if market_name not in self._subscriptions:
            self._subscriptions[market_name] = set()
        self._subscriptions[market_name].add(normalized_symbol)
        self._cache[normalized_symbol] = self._active_quote(normalized_symbol) or self._cache.get(normalized_symbol, {"symbol": normalized_symbol, "market_data_status": "DISCONNECTED"})

    def get_subscription_status(self, market_name: str, symbol: str) -> Dict[str, Any]:
        normalized_symbol = _normalize_symbol(symbol)
        quote = self._active_quote(normalized_symbol)
        status = self.get_provider_status(market_name)
        return {
            "market": market_name,
            "symbol": normalized_symbol,
            "provider_status": status["status"],
            "provider": status["provider"],
            "quote": quote,
            "cached_at": _now_iso(),
        }

    def market_snapshot(self, symbol: str) -> Dict[str, Any]:
        normalized_symbol = _normalize_symbol(symbol)
        market_name = _market_name_for_symbol(normalized_symbol)
        quote = self._active_quote(normalized_symbol)
        provider_status = self.get_provider_status(market_name)
        if quote is None:
            return {
                "symbol": normalized_symbol,
                "provider_status": provider_status["status"],
                "market_data_status": "DISCONNECTED",
                "quote": None,
                "data_source": "Yahoo Finance fallback",
                "cached_at": _now_iso(),
            }
        snapshot_status = "HISTORICAL" if quote.get("market_data_status") == "HISTORICAL" else provider_status["status"]
        return {
            "symbol": normalized_symbol,
            "provider_status": provider_status["status"],
            "market_data_status": snapshot_status,
            "quote": quote,
            "data_source": quote.get("provider", self._provider_handlers.get(market_name, {}).get("fallback", "Yahoo Finance")),
            "cached_at": _now_iso(),
        }

    def reconnect_delay(self, market_name: str) -> int:
        attempts = self._reconnect_attempts.get(market_name, 0)
        self._reconnect_attempts[market_name] = attempts + 1
        return min(30, 2 ** attempts)


market_data_service = MarketDataService()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.(app\.github\.dev|preview\.app\.github\.dev)|http://localhost:\d+|http://127\.0\.0\.1:\d+|https://localhost:\d+",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

FOREX_PAIRS = {
    "Major": ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD"],
    "Minor": ["EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF", "AUD/JPY", "GBP/CHF"],
    "Additional": ["USD/INR", "EUR/INR", "GBP/INR", "JPY/INR", "AUD/INR"],
}

FOREX_TICKERS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "USD/CHF": "CHF=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "CAD=X",
    "NZD/USD": "NZDUSD=X",
    "EUR/GBP": "EURGBP=X",
    "EUR/JPY": "EURJPY=X",
    "GBP/JPY": "GBPJPY=X",
    "EUR/CHF": "EURCHF=X",
    "AUD/JPY": "AUDJPY=X",
    "GBP/CHF": "GBPCHF=X",
    "USD/INR": "INR=X",
    "EUR/INR": "EURINR=X",
    "GBP/INR": "GBPINR=X",
    "JPY/INR": "JPYINR=X",
    "AUD/INR": "AUDINR=X",
}

INDIA_SYMBOLS = [
    ("RELIANCE.NS", "Reliance Industries"),
    ("TCS.NS", "Tata Consultancy Services"),
    ("HDFCBANK.NS", "HDFC Bank"),
    ("INFY.NS", "Infosys"),
    ("ICICIBANK.NS", "ICICI Bank"),
    ("SBIN.NS", "State Bank of India"),
    ("LTIM.NS", "LTIMindtree"),
]

US_SYMBOLS = [
    ("AAPL", "Apple Inc."),
    ("MSFT", "Microsoft"),
    ("NVDA", "NVIDIA"),
    ("AMZN", "Amazon"),
    ("TSLA", "Tesla"),
    ("META", "Meta"),
    ("GOOGL", "Alphabet"),
    ("NFLX", "Netflix"),
]

INDEX_SYMBOLS = [
    ("^NSEI", "NIFTY 50"),
    ("^NSEBANK", "BANK NIFTY"),
    ("^BSESN", "SENSEX"),
    ("^GSPC", "S&P 500"),
    ("^IXIC", "NASDAQ 100"),
    ("^DJI", "Dow Jones"),
]

MARKET_LIST = [
    {"category": "India", "items": [{"symbol": symbol, "name": name} for symbol, name in INDIA_SYMBOLS]},
    {"category": "United States", "items": [{"symbol": symbol, "name": name} for symbol, name in US_SYMBOLS]},
    {"category": "Indices", "items": [{"symbol": symbol, "name": name} for symbol, name in INDEX_SYMBOLS]},
    {"category": "Forex", "items": [{"symbol": pair, "name": pair} for pair in [item for group in FOREX_PAIRS.values() for item in group]]},
]

MARKET_CATEGORY_META = {
    "India": {"label": "Indian Markets", "description": "NSE/BSE equities and index coverage."},
    "United States": {"label": "US Markets", "description": "NASDAQ/NYSE and large-cap equity coverage."},
    "Indices": {"label": "Market Indices", "description": "Benchmark indexes covering major global segments."},
    "Forex": {"label": "Foreign Exchange", "description": "Major, minor and INR crosses."},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pair_precision(pair: str) -> int:
    return 3 if pair.endswith(("JPY", "INR")) else 5


def _normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        return ""
    return symbol.strip().upper().replace("-", "/")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _http_get_json(url: str, headers: Dict[str, str] | None = None, params: Dict[str, str] | None = None, timeout: int = 10) -> Any:
    final_url = url
    if params:
        final_url = f"{url}?{urlencode(params)}"
    request_obj = request.Request(final_url, headers=headers or {})
    try:
        with request.urlopen(request_obj, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)
    except Exception:
        return None


def _verify_market_provider(market_name: str):
    if market_name == "India":
        api_key = os.getenv("UPSTOX_API_KEY")
        client_code = os.getenv("UPSTOX_CLIENT_CODE")
        access_token = os.getenv("UPSTOX_ACCESS_TOKEN")
        if not api_key or not client_code or not access_token:
            return None
        headers = {
            "Accept": "application/json",
            "Api-Key": api_key,
            "Client-Code": client_code,
            "Authorization": f"Bearer {access_token}",
        }
        payload = _http_get_json("https://api.upstox.com/v2/user/profile", headers=headers, timeout=10)
        if payload is None:
            return {"status": "AUTHORIZED", "provider": "Upstox / authorized NSE-BSE market data", "checked_at": _now_iso()}
        if isinstance(payload, dict) and ("error" in payload or "message" in payload and "error" in str(payload["message"]).lower()):
            return {"status": "AUTHORIZED", "provider": "Upstox / authorized NSE-BSE market data", "checked_at": _now_iso()}
        return {"status": "LIVE", "provider": "Upstox / authorized NSE-BSE market data", "checked_at": _now_iso()}

    if market_name == "United States":
        api_key = os.getenv("ALPACA_API_KEY")
        api_secret = os.getenv("ALPACA_API_SECRET")
        if not api_key or not api_secret:
            return None
        payload = _http_get_json(
            f"{os.getenv('ALPACA_BASE_URL', 'https://data.alpaca.markets')}/v2/stocks/AAPL/quote/latest",
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
                "Accept": "application/json",
            },
            timeout=10,
        )
        if payload is None:
            return {"status": "AUTHORIZED", "provider": "Alpaca / authorized US market data", "checked_at": _now_iso()}
        if isinstance(payload, dict):
            if payload.get("status") == "error":
                return {"status": "AUTHORIZED", "provider": "Alpaca / authorized US market data", "checked_at": _now_iso()}
            if payload.get("symbol") or payload.get("last") is not None or payload.get("quote"):
                return {"status": "LIVE", "provider": "Alpaca / authorized US market data", "checked_at": _now_iso()}
            return {"status": "DELAYED", "provider": "Alpaca / authorized US market data", "checked_at": _now_iso()}
        return {"status": "DELAYED", "provider": "Alpaca / authorized US market data", "checked_at": _now_iso()}

    if market_name == "Forex":
        api_key = os.getenv("OANDA_API_KEY")
        account_id = os.getenv("OANDA_ACCOUNT_ID")
        if not api_key or not account_id:
            return None
        payload = _http_get_json(
            f"https://api-fxtrade.oanda.com/v3/accounts/{account_id}/pricing",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Accept-Datetime-Format": "unix",
            },
            params={"instruments": "EUR_USD"},
            timeout=10,
        )
        if payload is None:
            return {"status": "AUTHORIZED", "provider": "OANDA / authorized FX streaming provider", "checked_at": _now_iso()}
        if isinstance(payload, dict):
            if payload.get("errorMessage") or payload.get("error"):
                return {"status": "AUTHORIZED", "provider": "OANDA / authorized FX streaming provider", "checked_at": _now_iso()}
            if payload.get("prices"):
                return {"status": "LIVE", "provider": "OANDA / authorized FX streaming provider", "checked_at": _now_iso()}
            return {"status": "DELAYED", "provider": "OANDA / authorized FX streaming provider", "checked_at": _now_iso()}
        return {"status": "DELAYED", "provider": "OANDA / authorized FX streaming provider", "checked_at": _now_iso()}

    return None


def get_market_status() -> Dict[str, Any]:
    return market_data_service.get_market_status()


def _symbol_name(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    for section in MARKET_LIST:
        for item in section["items"]:
            if _normalize_symbol(item["symbol"]) == normalized:
                return item["name"]
    return normalized


def _history_from_yahoo(symbol: str, period: str = "5d", interval: str = "1d") -> pd.DataFrame:
    data = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    if getattr(data, "empty", True):
        return pd.DataFrame()
    df = data.copy()
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    return df[["open", "high", "low", "close", "volume"]].dropna()


def _quote_from_yahoo(symbol: str, market_name: str | None = None) -> Dict[str, Any] | None:
    normalized_symbol = _normalize_symbol(symbol)
    history = _history_from_yahoo(normalized_symbol, period="5d", interval="1d")
    if history.empty:
        return None
    latest = history.iloc[-1]
    previous = history.iloc[-2] if len(history) > 1 else latest
    close = _as_float(latest["close"])
    previous_close = _as_float(previous["close"])
    change = close - previous_close
    change_percent = (change / previous_close * 100.0) if previous_close else 0.0
    return {
        "symbol": normalized_symbol,
        "name": _symbol_name(normalized_symbol),
        "price": round(close, 2 if normalized_symbol not in {"USD/JPY", "USD/INR", "JPY/INR", "EUR/INR", "GBP/INR"} else 3),
        "previous_close": round(previous_close, 2 if normalized_symbol not in {"USD/JPY", "USD/INR", "JPY/INR", "EUR/INR", "GBP/INR"} else 3),
        "change": round(change, 2 if normalized_symbol not in {"USD/JPY", "USD/INR", "JPY/INR", "EUR/INR", "GBP/INR"} else 3),
        "change_percent": round(change_percent, 2),
        "high": round(_as_float(latest.get("high", close)), 2 if normalized_symbol not in {"USD/JPY", "USD/INR", "JPY/INR", "EUR/INR", "GBP/INR"} else 3),
        "low": round(_as_float(latest.get("low", close)), 2 if normalized_symbol not in {"USD/JPY", "USD/INR", "JPY/INR", "EUR/INR", "GBP/INR"} else 3),
        "volume": int(_as_float(latest.get("volume", 0))),
        "currency": "INR" if normalized_symbol.endswith(".NS") else "USD" if normalized_symbol.startswith("^") or not any(x in normalized_symbol for x in ["/", "JPY", "INR"]) else "USD",
        "market_data_status": "HISTORICAL",
        "provider": "Yahoo Finance",
        "last_updated": pd.Timestamp(latest.name).tz_localize("UTC").isoformat() if pd.Timestamp(latest.name).tzinfo is None else pd.Timestamp(latest.name).tz_convert("UTC").isoformat(),
    }


def _fetch_forex_quote(pair: str) -> Dict[str, Any] | None:
    normalized_pair = _normalize_symbol(pair)
    ticker = FOREX_TICKERS.get(normalized_pair)
    if not ticker:
        return None
    history = _history_from_yahoo(ticker, period="5d", interval="1d")
    if history.empty:
        return None
    latest = history.iloc[-1]
    previous = history.iloc[-2] if len(history) > 1 else latest
    price = _as_float(latest["close"])
    prev_close = _as_float(previous["close"])
    change = price - prev_close
    change_pct = (change / prev_close * 100.0) if prev_close else 0.0
    precision = _pair_precision(normalized_pair)
    spread = abs(price * 0.0002) if normalized_pair.endswith(("USD", "CHF", "CAD")) else abs(price * 0.00045)
    bid = round(price - spread, precision)
    ask = round(price + spread, precision)
    return {
        "pair": normalized_pair,
        "price": round(price, precision),
        "bid": round(bid, precision),
        "ask": round(ask, precision),
        "spread": round(abs(ask - bid), precision),
        "daily_change_pct": round(change_pct, 4),
        "daily_high": round(_as_float(latest["high"]), precision),
        "daily_low": round(_as_float(latest["low"]), precision),
        "daily_volume": int(_as_float(latest.get("volume", 0))),
        "session": "London" if normalized_pair in {"EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/CHF"} else "New York",
        "strength": "Bullish" if change_pct > 0 else "Bearish" if change_pct < 0 else "Neutral",
        "provider": "Yahoo Finance",
        "market_data_status": "HISTORICAL",
        "last_updated": pd.Timestamp(latest.name).tz_localize("UTC").isoformat() if pd.Timestamp(latest.name).tzinfo is None else pd.Timestamp(latest.name).tz_convert("UTC").isoformat(),
    }


def _fetch_upstox_quote(symbol: str) -> Dict[str, Any] | None:
    normalized_symbol = _normalize_symbol(symbol)
    api_key = os.getenv("UPSTOX_API_KEY")
    client_code = os.getenv("UPSTOX_CLIENT_CODE")
    access_token = os.getenv("UPSTOX_ACCESS_TOKEN")
    if not api_key or not client_code or not access_token:
        return None
    instrument_name = normalized_symbol.replace(".NS", "")
    if not instrument_name:
        return None
    payload = _http_get_json(
        "https://api.upstox.com/v2/market-quote/quotes",
        headers={
            "Accept": "application/json",
            "Api-Key": api_key,
            "Client-Code": client_code,
            "Authorization": f"Bearer {access_token}",
        },
        params={"instrument_key": f"NSE_EQ|{instrument_name}"},
        timeout=10,
    )
    if not payload or not isinstance(payload, dict):
        return None
    quote = payload.get("data", {}).get("quote") or payload.get("data") or payload
    if not isinstance(quote, dict):
        return None
    last_price = _as_float(quote.get("last_price") or quote.get("ltp") or quote.get("close"))
    if last_price <= 0:
        return None
    close = _as_float(quote.get("close", last_price))
    high = _as_float(quote.get("high", last_price))
    low = _as_float(quote.get("low", last_price))
    prev_close = _as_float(quote.get("previous_close", close))
    change = close - prev_close
    change_percent = (change / prev_close * 100.0) if prev_close else 0.0
    return {
        "symbol": normalized_symbol,
        "name": _symbol_name(normalized_symbol),
        "price": round(last_price, 2),
        "previous_close": round(prev_close, 2),
        "change": round(change, 2),
        "change_percent": round(change_percent, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "volume": int(_as_float(quote.get("volume", 0))),
        "currency": "INR",
        "market_data_status": "LIVE",
        "provider": "Upstox",
        "last_updated": _now_iso(),
    }


def _fetch_alpaca_quote(symbol: str) -> Dict[str, Any] | None:
    normalized_symbol = _normalize_symbol(symbol)
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        return None
    ticker = normalized_symbol.replace(".NS", "")
    payload = _http_get_json(
        f"{os.getenv('ALPACA_BASE_URL', 'https://data.alpaca.markets')}/v2/stocks/{ticker}/quote/latest",
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Accept": "application/json",
        },
        timeout=10,
    )
    if not payload or not isinstance(payload, dict):
        return None
    quote = payload.get("quote") if isinstance(payload.get("quote"), dict) else payload
    if not isinstance(quote, dict):
        return None
    price = _as_float(quote.get("last"))
    if price <= 0:
        return None
    previous_close = _as_float(quote.get("previous_close", price))
    change = price - previous_close
    change_percent = (change / previous_close * 100.0) if previous_close else 0.0
    return {
        "symbol": normalized_symbol,
        "name": _symbol_name(normalized_symbol),
        "price": round(price, 2),
        "previous_close": round(previous_close, 2),
        "change": round(change, 2),
        "change_percent": round(change_percent, 2),
        "high": round(_as_float(quote.get("high", price)), 2),
        "low": round(_as_float(quote.get("low", price)), 2),
        "volume": int(_as_float(quote.get("volume", 0))),
        "currency": "USD",
        "market_data_status": "LIVE",
        "provider": "Alpaca",
        "last_updated": _now_iso(),
    }


def _fetch_oanda_quote(pair: str) -> Dict[str, Any] | None:
    normalized_pair = _normalize_symbol(pair)
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    if not api_key or not account_id:
        return None
    payload = _http_get_json(
        f"https://api-fxtrade.oanda.com/v3/accounts/{account_id}/pricing",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Accept-Datetime-Format": "unix",
        },
        params={"instruments": normalized_pair.replace("/", "_")},
        timeout=10,
    )
    if not payload or not isinstance(payload, dict):
        return None
    prices = payload.get("prices")
    if not isinstance(prices, list) or not prices:
        return None
    first = prices[0]
    asks = first.get("asks") or []
    bids = first.get("bids") or []
    if not asks or not bids:
        return None
    ask = _as_float(asks[0].get("price"))
    bid = _as_float(bids[0].get("price"))
    mid = (ask + bid) / 2.0
    precision = _pair_precision(normalized_pair)
    previous_close = mid
    change = 0.0
    change_percent = 0.0
    return {
        "pair": normalized_pair,
        "price": round(mid, precision),
        "bid": round(bid, precision),
        "ask": round(ask, precision),
        "spread": round(abs(ask - bid), precision),
        "daily_change_pct": round(change_percent, 4),
        "daily_high": round(mid, precision),
        "daily_low": round(mid, precision),
        "daily_volume": 0,
        "session": "Live",
        "strength": "Neutral",
        "provider": "OANDA",
        "market_data_status": "LIVE",
        "last_updated": _now_iso(),
    }


def _get_quote_for_symbol(symbol: str) -> Dict[str, Any] | None:
    normalized = _normalize_symbol(symbol)
    if not normalized:
        return None

    if any(pair in normalized for pair in ["/", "USD", "EUR", "GBP", "JPY", "INR"]) and normalized in FOREX_TICKERS:
        if os.getenv("OANDA_API_KEY") and os.getenv("OANDA_ACCOUNT_ID"):
            quote = _fetch_oanda_quote(normalized)
            if quote is not None:
                return quote
        return _fetch_forex_quote(normalized)
    if normalized.endswith(".NS") and os.getenv("UPSTOX_API_KEY") and os.getenv("UPSTOX_CLIENT_CODE") and os.getenv("UPSTOX_ACCESS_TOKEN"):
        quote = _fetch_upstox_quote(normalized)
        if quote is not None:
            return quote
    if any(marker in normalized for marker in ["^", "AAPL", "MSFT", "NVDA", "AMZN", "TSLA", "META", "GOOGL", "NFLX"]) and os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET"):
        quote = _fetch_alpaca_quote(normalized)
        if quote is not None:
            return quote
    if normalized.endswith(".NS"):
        return _quote_from_yahoo(normalized, "stock")
    return _quote_from_yahoo(normalized, "stock")


@app.get("/")
def home() -> Dict[str, Any]:
    return {
        "project": "QUANT-X",
        "message": "Global market intelligence service is online.",
        "status": "online",
        "timestamp": _now_iso(),
    }


@app.get("/health")
def health_check() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "backend": "operational",
        "market_data_status": "HISTORICAL_ONLY",
        "timestamp": _now_iso(),
    }


@app.get("/api/market-status")
def market_status() -> Dict[str, Any]:
    return get_market_status()


@app.get("/api/provider-status")
def get_provider_status() -> Dict[str, Any]:
    providers = {}
    for name in MARKET_PROVIDER_REQUIREMENTS:
        status = market_data_service.get_provider_status(name)
        providers[name] = {
            **status,
            "subscription_count": len(market_data_service._subscriptions.get(name, set())),
            "reconnect_delay_seconds": market_data_service.reconnect_delay(name),
            "data_source": "Yahoo Finance fallback" if status["status"] == "DISCONNECTED" else "Active provider" if status["status"] == "LIVE" else "Provider configured but unverified",
        }
    return {
        "providers": providers,
        "active_status": market_data_service.get_market_status(),
        "timestamp": _now_iso(),
    }


@app.get("/api/markets")
def get_markets() -> Dict[str, Any]:
    status = get_market_status()
    return {
        "markets": [entry["category"] for entry in MARKET_LIST],
        "data_provider": status["warning"],
        "trading_mode": "Paper Trading Only",
        "provider_status": status["markets"],
    }


@app.get("/api/market-list")
def get_market_list() -> Dict[str, Any]:
    status = get_market_status()
    markets: List[Dict[str, Any]] = []
    for entry in MARKET_LIST:
        category = entry["category"]
        items: List[Dict[str, Any]] = []
        for item in entry["items"]:
            quote = _get_quote_for_symbol(item["symbol"])
            if quote is None:
                items.append({
                    "symbol": item["symbol"],
                    "name": item["name"],
                    "price": None,
                    "change_percent": None,
                    "market_data_status": "HISTORICAL",
                    "provider": "Yahoo Finance",
                    "last_updated": _now_iso(),
                })
                continue
            payload = {
                "symbol": item["symbol"],
                "name": item["name"],
                "price": quote.get("price"),
                "change": quote.get("change"),
                "change_percent": quote.get("change_percent"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "volume": quote.get("volume"),
                "market_data_status": quote.get("market_data_status", "HISTORICAL"),
                "provider": quote.get("provider", "Yahoo Finance"),
                "last_updated": quote.get("last_updated", _now_iso()),
            }
            items.append(payload)
        markets.append({"category": category, "items": items})
    return {"markets": markets, "provider_status": status["markets"], "timestamp": _now_iso()}


@app.get("/api/market-overview")
def get_market_overview() -> Dict[str, Any]:
    status = get_market_status()
    markets = get_market_list()["markets"]
    watchlist = ["RELIANCE.NS", "TCS.NS", "AAPL", "MSFT", "^NSEI", "EUR/USD"]
    active_markets = [entry["category"] for entry in markets if entry["items"]]
    top_gainers = []
    top_losers = []
    for entry in markets:
        for item in entry["items"]:
            if item.get("change_percent") is None:
                continue
            bucket = top_gainers if float(item["change_percent"]) >= 0 else top_losers
            bucket.append(item)
    top_gainers = sorted(top_gainers, key=lambda item: float(item.get("change_percent") or 0.0), reverse=True)[:5]
    top_losers = sorted(top_losers, key=lambda item: float(item.get("change_percent") or 0.0))[:5]
    return {
        "status": status["status"],
        "markets": markets,
        "watchlist": watchlist,
        "provider_status": status["markets"],
        "market_overview": {
            "categories": active_markets,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "last_updated": _now_iso(),
        },
        "warning": status["warning"],
        "timestamp": _now_iso(),
    }


@app.get("/api/stock/{symbol}")
def get_stock(symbol: str) -> Dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    quote = _get_quote_for_symbol(normalized_symbol)
    if quote is None:
        raise HTTPException(status_code=404, detail=f"No market data found for {normalized_symbol}.")
    return {
        "symbol": normalized_symbol,
        "name": _symbol_name(normalized_symbol),
        **quote,
    }


@app.get("/api/search")
def search_market(query: str = Query(default="")) -> Dict[str, Any]:
    search_term = query.strip().lower()
    results: List[Dict[str, Any]] = []
    if not search_term:
        return {"results": results}
    for entry in MARKET_LIST:
        for item in entry["items"]:
            symbol = item["symbol"]
            name = item["name"]
            if search_term in symbol.lower() or search_term in name.lower():
                quote = _get_quote_for_symbol(symbol)
                if quote is not None:
                    results.append({"symbol": symbol, "name": name, "price": quote.get("price"), "change_percent": quote.get("change_percent"), "market_data_status": quote.get("market_data_status", "HISTORICAL")})
    return {"results": results}


@app.get("/api/history/{symbol}")
def get_history(
    symbol: str,
    period: str = Query(default="1mo", pattern="^(5d|1mo|3mo|6mo|1y|2y)$"),
    interval: str = Query(default="1d", pattern="^(1m|5m|15m|30m|1h|4h|1d|1wk)$"),
) -> Dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    history = _history_from_yahoo(normalized_symbol, period=period, interval=interval)
    if history.empty:
        raise HTTPException(status_code=404, detail=f"No historical data found for {normalized_symbol}.")
    records: List[Dict[str, Any]] = []
    for timestamp, row in history.iterrows():
        ts = pd.Timestamp(timestamp)
        records.append({
            "time": int(ts.timestamp()),
            "open": round(_as_float(row.get("open", 0)), 2),
            "high": round(_as_float(row.get("high", 0)), 2),
            "low": round(_as_float(row.get("low", 0)), 2),
            "close": round(_as_float(row.get("close", 0)), 2),
            "volume": int(_as_float(row.get("volume", 0))),
        })
    return {"symbol": normalized_symbol, "period": period, "interval": interval, "provider": "Yahoo Finance", "data": records}


@app.get("/api/chart/{symbol}")
def get_chart(
    symbol: str,
    interval: str = Query(default="1d", pattern="^(1m|3m|5m|15m|30m|1h|2h|4h|1d|1wk|1mo)$"),
    period: str = Query(default="1mo"),
    limit: int = Query(default=200, ge=20, le=500),
) -> Dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    history = _history_from_yahoo(normalized_symbol, period=period, interval=interval)
    if history.empty:
        raise HTTPException(status_code=404, detail=f"No chart data found for {normalized_symbol}.")
    records: List[Dict[str, Any]] = []
    for timestamp, row in history.tail(limit).iterrows():
        ts = pd.Timestamp(timestamp)
        records.append({
            "time": int(ts.timestamp()),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(float(row["volume"])),
        })
    return {"symbol": normalized_symbol, "interval": interval, "period": period, "candles": records}


def _to_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    ha = pd.DataFrame(index=df.index)
    ha["close"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    ha["open"] = 0.0
    for idx in range(len(df)):
        if idx == 0:
            ha.at[df.index[idx], "open"] = (df["open"].iloc[idx] + df["close"].iloc[idx]) / 2.0
        else:
            ha.at[df.index[idx], "open"] = (ha["open"].iloc[idx - 1] + ha["close"].iloc[idx - 1]) / 2.0
    ha["high"] = df[["high", "open", "close"]].max(axis=1)
    ha["low"] = df[["low", "open", "close"]].min(axis=1)
    return ha


def _compute_indicator_summary(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {}

    closes = df["close"].astype(float)
    opens = df["open"].astype(float)
    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    volumes = df["volume"].astype(float)

    sma = closes.rolling(window=20, min_periods=1).mean()
    ema = closes.ewm(span=20, adjust=False).mean()
    typical_price = (highs + lows + closes) / 3.0
    vwap = (typical_price * volumes).cumsum() / volumes.cumsum().replace(0, np.nan)

    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=14, min_periods=1).mean()
    avg_loss = loss.rolling(window=14, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    ema_fast = closes.ewm(span=12, adjust=False).mean()
    ema_slow = closes.ewm(span=26, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=9, adjust=False).mean()

    bollinger_mid = closes.rolling(window=20, min_periods=1).mean()
    bollinger_std = closes.rolling(window=20, min_periods=1).std()
    upper_band = bollinger_mid + (2 * bollinger_std)
    lower_band = bollinger_mid - (2 * bollinger_std)

    atr_values = []
    for position, row in enumerate(df.itertuples(index=True)):
        if position == 0:
            atr_values.append(float(row.high) - float(row.low))
            continue
        previous = df.iloc[position - 1]
        true_range = max(
            float(row.high) - float(row.low),
            abs(float(row.high) - float(previous["close"])),
            abs(float(row.low) - float(previous["close"])),
        )
        atr_values.append(float(true_range))
    atr = pd.Series(atr_values, index=df.index)

    stoch_k = []
    for idx in range(len(df)):
        low_window = lows.iloc[max(0, idx - 13): idx + 1]
        high_window = highs.iloc[max(0, idx - 13): idx + 1]
        window_low = float(low_window.min())
        window_high = float(high_window.max())
        value = 50.0 if window_high == window_low else ((closes.iloc[idx] - window_low) / (window_high - window_low)) * 100.0
        stoch_k.append(value)

    ha = _to_heikin_ashi(df)
    return {
        "SMA": [float(value) for value in sma.tolist()],
        "EMA": [float(value) for value in ema.tolist()],
        "VWAP": [float(value) for value in vwap.tolist()],
        "RSI": [float(value) for value in rsi.tolist()],
        "MACD": [float(value) for value in (macd - signal_line).tolist()],
        "Bollinger Bands": {
            "upper": [float(value) for value in upper_band.tolist()],
            "mid": [float(value) for value in bollinger_mid.tolist()],
            "lower": [float(value) for value in lower_band.tolist()],
        },
        "ATR": [float(value) for value in atr.tolist()],
        "Stochastic": [float(value) for value in stoch_k],
        "Volume": [float(value) for value in volumes.tolist()],
        "Heikin-Ashi": {
            "open": [float(value) for value in ha["open"].tolist()],
            "high": [float(value) for value in ha["high"].tolist()],
            "low": [float(value) for value in ha["low"].tolist()],
            "close": [float(value) for value in ha["close"].tolist()],
        },
    }


@app.get("/api/indicators/{symbol}")
def get_indicator_summary(
    symbol: str,
    interval: str = Query(default="1d", pattern="^(1m|3m|5m|15m|30m|1h|2h|4h|1d|1wk|1mo)$"),
    period: str = Query(default="1mo"),
    limit: int = Query(default=200, ge=20, le=500),
) -> Dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    history = _history_from_yahoo(normalized_symbol, period=period, interval=interval)
    if history.empty:
        raise HTTPException(status_code=404, detail=f"No indicator data found for {normalized_symbol}.")
    series = history.tail(limit).copy()
    records: List[Dict[str, Any]] = []
    for timestamp, row in series.iterrows():
        ts = pd.Timestamp(timestamp)
        records.append({
            "time": int(ts.timestamp()),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(float(row["volume"])),
        })
    summary = _compute_indicator_summary(series)
    return {
        "symbol": normalized_symbol,
        "interval": interval,
        "period": period,
        "candles": records,
        "indicators": summary,
    }


@app.get("/api/forex/pairs")
def get_forex_pairs() -> Dict[str, Any]:
    flattened = [item for group in FOREX_PAIRS.values() for item in group]
    return {"pairs": FOREX_PAIRS, "supported_count": len(flattened), "data_note": "Quotes are historical fallback values unless your OANDA credentials are configured."}


@app.get("/api/forex/dashboard")
def get_forex_dashboard() -> Dict[str, Any]:
    status = get_market_status()
    quotes: List[Dict[str, Any]] = []
    flattened = [item for group in FOREX_PAIRS.values() for item in group]
    for pair in flattened:
        quote = _fetch_forex_quote(pair)
        if quote is not None:
            quotes.append(quote)
    watchlist = [pair for pair in ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "USD/INR"] if any(q["pair"] == pair for q in quotes)]
    watchlist_quotes = [q for q in quotes if q["pair"] in watchlist]
    strongest = sorted(quotes, key=lambda q: q["daily_change_pct"], reverse=True)[:5]
    weakest = sorted(quotes, key=lambda q: q["daily_change_pct"])[:5]
    return {
        "provider": status["markets"]["Forex"]["provider"],
        "data_status": status["markets"]["Forex"]["status"],
        "last_updated": _now_iso(),
        "session_status": {
            "Sydney": {"status": "Open", "local": "Market active", "timezone": "AEST", "hours": "10:00-19:00"},
            "Tokyo": {"status": "Open", "local": "Market active", "timezone": "JST", "hours": "09:00-18:00"},
            "London": {"status": "Open", "local": "Market active", "timezone": "GMT", "hours": "08:00-17:00"},
            "New York": {"status": "Open", "local": "Market active", "timezone": "EST", "hours": "13:00-22:00"},
        },
        "watchlist": watchlist_quotes,
        "currency_strength": {"strongest": [q["pair"] for q in strongest], "weakest": [q["pair"] for q in weakest]},
        "heatmap": sorted(quotes, key=lambda q: q["daily_change_pct"], reverse=True),
        "economic_calendar": [
            {"event": "US CPI Release", "impact": "High", "time": "08:30 ET", "currency": "USD"},
            {"event": "ECB Policy Statement", "impact": "High", "time": "09:00 CET", "currency": "EUR"},
            {"event": "BoJ Rate Decision", "impact": "Medium", "time": "03:00 JST", "currency": "JPY"},
            {"event": "RBA Minutes", "impact": "Medium", "time": "00:30 AEDT", "currency": "AUD"},
        ],
        "providers": [
            {"name": "OANDA", "free_plan": "Demo/limited delayed data", "pairs": "Major + minors", "streaming": "Yes", "rate_limit": "Moderate"},
            {"name": "Yahoo Finance", "free_plan": "Historical data access", "pairs": "Major + exotics", "streaming": "No", "rate_limit": "Moderate"},
        ],
    }


@app.get("/api/forex/quote/{pair}")
def get_forex_quote(pair: str) -> Dict[str, Any]:
    normalized = pair.upper().replace("-", "/")
    if normalized not in {item for group in FOREX_PAIRS.values() for item in group}:
        raise HTTPException(status_code=404, detail="Currency pair not supported in the QUANT-X FX universe.")
    quote = _fetch_forex_quote(normalized)
    if quote is None:
        raise HTTPException(status_code=404, detail=f"No FX data found for {normalized}.")
    quote["signal"] = get_forex_signal(normalized)
    return quote


@app.get("/api/forex/signal/{pair}")
def get_forex_signal(pair: str) -> Dict[str, Any]:
    normalized = pair.upper().replace("-", "/")
    valid_pairs = {item for group in FOREX_PAIRS.values() for item in group}
    if normalized not in valid_pairs:
        raise ValueError(f"{pair} is not a supported currency pair.")
    quote = _fetch_forex_quote(normalized) or {"price": 1.0, "daily_change_pct": 0.0}
    change = quote["daily_change_pct"]
    if change > 0.25:
        signal = "BUY"
        entry = quote["price"]
        stop_loss = entry * (1 - 0.006)
        take_profit = entry * (1 + 0.012)
        explanation = "Positive daily momentum and a firm support structure.",
    elif change < -0.25:
        signal = "SELL"
        entry = quote["price"]
        stop_loss = entry * (1 + 0.006)
        take_profit = entry * (1 - 0.012)
        explanation = "Weak trend structure and downside continuation pressure.",
    else:
        signal = "HOLD"
        entry = quote["price"]
        stop_loss = entry * (1 - 0.005)
        take_profit = entry * (1 + 0.008)
        explanation = "Range-bound structure; wait for confirmation.",
    rr = max(1.0, round((take_profit - entry) / max(entry - stop_loss, 0.0001), 2))
    return {
        "pair": normalized,
        "signal": signal,
        "entry_price": round(entry, _pair_precision(normalized)),
        "stop_loss": round(stop_loss, _pair_precision(normalized)),
        "take_profit": round(take_profit, _pair_precision(normalized)),
        "risk_reward_ratio": rr,
        "prediction_confidence": round(0.78 if signal == "BUY" else 0.76 if signal == "SELL" else 0.6, 2),
        "timestamp": _now_iso(),
        "signal_explanation": explanation[0] if isinstance(explanation, tuple) else explanation,
    }


@app.get("/api/forex/heatmap")
def get_forex_heatmap() -> Dict[str, Any]:
    flattened = [item for group in FOREX_PAIRS.values() for item in group]
    quotes = [q for q in [_fetch_forex_quote(pair) for pair in flattened] if q is not None]
    return {"pairs": quotes}


def _calculate_indicators(df: pd.DataFrame, strategy: str) -> Dict[str, Any]:
    closes = df["close"].astype(float)
    if strategy == "moving_average_crossover":
        short = closes.rolling(10).mean()
        long = closes.rolling(30).mean()
        return {"signal": np.where(short > long, 1, 0).tolist(), "short": short.tolist(), "long": long.tolist()}
    if strategy == "rsi":
        delta = closes.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return {"signal": rsi.tolist(), "rsi": rsi.tolist()}
    if strategy == "macd":
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        return {"signal": (macd - signal).tolist(), "macd": macd.tolist(), "signal_line": signal.tolist()}
    if strategy == "bollinger":
        sma = closes.rolling(20).mean()
        std = closes.rolling(20).std()
        upper = sma + (2 * std)
        lower = sma - (2 * std)
        return {"signal": upper.tolist(), "upper": upper.tolist(), "mid": sma.tolist(), "lower": lower.tolist()}
    if strategy == "supertrend":
        atr = closes.rolling(14).std().fillna(0)
        return {"signal": (closes - atr).tolist(), "supertrend": (closes - atr).tolist()}
    return {"signal": closes.tolist()}


def _strategy_signal(df: pd.DataFrame, strategy: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    params = params or {}
    closes = df["close"].astype(float)
    if strategy == "moving_average_crossover":
        short = closes.rolling(int(params.get("short_window", 10))).mean()
        long = closes.rolling(int(params.get("long_window", 30))).mean()
        if short.iloc[-1] > long.iloc[-1]:
            signal = "BUY"
        elif short.iloc[-1] < long.iloc[-1]:
            signal = "SELL"
        else:
            signal = "HOLD"
        return {"signal": signal, "entry_price": float(closes.iloc[-1]), "stop_loss": float(closes.iloc[-1] * 0.98), "target_price": float(closes.iloc[-1] * 1.04), "timestamp": _now_iso(), "explanation": "Short-term moving average is above the longer-term average."}

    if strategy == "rsi":
        delta = closes.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(int(params.get("rsi_period", 14))).mean()
        avg_loss = loss.rolling(int(params.get("rsi_period", 14))).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        value = float(rsi.iloc[-1])
        if value < 30:
            signal = "BUY"
            explanation = "RSI is in oversold territory; momentum is recovering."
        elif value > 70:
            signal = "SELL"
            explanation = "RSI is in overbought territory; momentum is rolling over."
        else:
            signal = "HOLD"
            explanation = "RSI is neutral, so the trend remains balanced."
        return {"signal": signal, "entry_price": float(closes.iloc[-1]), "stop_loss": float(closes.iloc[-1] * 0.98), "target_price": float(closes.iloc[-1] * 1.06), "timestamp": _now_iso(), "explanation": explanation}

    if strategy == "macd":
        ema12 = closes.ewm(span=int(params.get("fast_period", 12)), adjust=False).mean()
        ema26 = closes.ewm(span=int(params.get("slow_period", 26)), adjust=False).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=int(params.get("signal_period", 9)), adjust=False).mean()
        hist = macd - signal_line
        if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
            signal = "BUY"
            explanation = "MACD histogram has crossed above zero and is expanding."
        elif hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
            signal = "SELL"
            explanation = "MACD histogram has crossed below zero and is weakening."
        else:
            signal = "HOLD"
            explanation = "MACD remains directionless around the zero line."
        return {"signal": signal, "entry_price": float(closes.iloc[-1]), "stop_loss": float(closes.iloc[-1] * 0.97), "target_price": float(closes.iloc[-1] * 1.06), "timestamp": _now_iso(), "explanation": explanation}

    if strategy == "bollinger":
        sma = closes.rolling(int(params.get("period", 20))).mean()
        std = closes.rolling(int(params.get("period", 20))).std()
        upper = sma + (2 * std)
        lower = sma - (2 * std)
        last_close = float(closes.iloc[-1])
        if last_close <= lower.iloc[-1]:
            signal = "BUY"
            explanation = "Price is near the lower band and may be oversold."
        elif last_close >= upper.iloc[-1]:
            signal = "SELL"
            explanation = "Price is near the upper band and may be stretched."
        else:
            signal = "HOLD"
            explanation = "Price is inside the Bollinger range and not yet confirmed."
        return {"signal": signal, "entry_price": last_close, "stop_loss": float(lower.iloc[-1]), "target_price": float(upper.iloc[-1]), "timestamp": _now_iso(), "explanation": explanation}

    if strategy == "supertrend":
        atr = closes.rolling(14).std().fillna(0)
        trend = closes - atr
        last_close = float(closes.iloc[-1])
        if trend.iloc[-1] > trend.iloc[-2]:
            signal = "BUY"
            explanation = "Trend remains positive as the rolling trend indicator expands upward."
        elif trend.iloc[-1] < trend.iloc[-2]:
            signal = "SELL"
            explanation = "Trend has rolled down and pressure is descending."
        else:
            signal = "HOLD"
            explanation = "Supertrend is flat and the market is waiting for a breakout."
        return {"signal": signal, "entry_price": last_close, "stop_loss": float(last_close * 0.97), "target_price": float(last_close * 1.06), "timestamp": _now_iso(), "explanation": explanation}

    signal = "HOLD"
    return {"signal": signal, "entry_price": float(closes.iloc[-1]), "stop_loss": float(closes.iloc[-1] * 0.97), "target_price": float(closes.iloc[-1] * 1.06), "timestamp": _now_iso(), "explanation": "No directional structure triggered."}


def _compute_backtest_metrics(series: Iterable[float]) -> Dict[str, Any]:
    values = list(series)
    if not values:
        return {"total_return": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0, "trade_count": 0}
    cumulative = np.cumprod(np.array([1.0 + float(v) for v in values], dtype=float))
    total_return = float(cumulative[-1] - 1.0)
    wins = sum(1 for v in values if v > 0)
    win_rate = wins / len(values) if values else 0.0
    gross_profit = sum(v for v in values if v > 0)
    gross_loss = abs(sum(v for v in values if v < 0))
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")
    running_peak = np.maximum.accumulate(cumulative)
    drawdown = (cumulative / running_peak) - 1.0
    max_drawdown = float(np.min(drawdown)) if len(drawdown) else 0.0
    return {"total_return": round(total_return, 4), "win_rate": round(win_rate, 4), "profit_factor": round(profit_factor, 4) if np.isfinite(profit_factor) else float("inf"), "max_drawdown": round(max_drawdown, 4), "trade_count": len(values)}


@app.get("/api/strategies/backtest")
def backtest_strategy(
    strategy: str = Query(default="moving_average_crossover"),
    symbol: str = Query(default="AAPL"),
    timeframe: str = Query(default="1d"),
    period: str = Query(default="1y"),
    short_window: int = Query(default=10),
    long_window: int = Query(default=30),
    rsi_period: int = Query(default=14),
) -> Dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    history = _history_from_yahoo(normalized_symbol, period=period, interval=timeframe)
    if history.empty:
        raise HTTPException(status_code=404, detail=f"No historical data available for {normalized_symbol}.")
    df = history.copy().reset_index()
    if "Date" in df.columns:
        df = df.rename(columns={"Date": "timestamp"})
    if df.empty:
        raise HTTPException(status_code=404, detail="Backtest data is empty.")

    params = {"short_window": short_window, "long_window": long_window, "rsi_period": rsi_period}
    signal = _strategy_signal(df, strategy, params)
    if strategy == "moving_average_crossover":
        short = df["close"].rolling(short_window).mean()
        long = df["close"].rolling(long_window).mean()
        position = np.where(short > long, 1, 0)
        strategy_returns = df["close"].pct_change().fillna(0).to_numpy() * position[:-1]
    elif strategy == "rsi":
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(rsi_period).mean()
        avg_loss = loss.rolling(rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        position = np.where(rsi < 30, 1, np.where(rsi > 70, -1, 0))
        strategy_returns = df["close"].pct_change().fillna(0).to_numpy() * position[:-1]
    elif strategy == "macd":
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9, adjust=False).mean()
        position = np.where(macd > signal_line, 1, np.where(macd < signal_line, -1, 0))
        strategy_returns = df["close"].pct_change().fillna(0).to_numpy() * position[:-1]
    elif strategy == "bollinger":
        sma = df["close"].rolling(20).mean()
        std = df["close"].rolling(20).std()
        upper = sma + (2 * std)
        lower = sma - (2 * std)
        position = np.where(df["close"] <= lower, 1, np.where(df["close"] >= upper, -1, 0))
        strategy_returns = df["close"].pct_change().fillna(0).to_numpy() * position[:-1]
    elif strategy == "supertrend":
        atr = df["close"].rolling(14).std().fillna(0)
        trend = df["close"] - atr
        position = np.where(trend > trend.shift(1), 1, np.where(trend < trend.shift(1), -1, 0))
        strategy_returns = df["close"].pct_change().fillna(0).to_numpy() * position[:-1]
    else:
        strategy_returns = df["close"].pct_change().fillna(0).to_numpy()

    metrics = _compute_backtest_metrics(strategy_returns)
    return {
        "symbol": normalized_symbol,
        "strategy": strategy,
        "timeframe": timeframe,
        "period": period,
        "signal": signal,
        "summary": {
            "total_return": metrics["total_return"],
            "win_rate": metrics["win_rate"],
            "profit_factor": metrics["profit_factor"],
            "max_drawdown": metrics["max_drawdown"],
            "transaction_cost": 0.001,
            "slippage": 0.0005,
            "entries": 1,
            "time_horizon": period,
        },
        "trade_history": [{"timestamp": _now_iso(), "action": signal["signal"], "price": signal["entry_price"], "reason": signal["explanation"]}],
        "provider": "Yahoo Finance historical data",
    }


@app.post("/api/paper-trading/order")
def paper_trade_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(payload.get("symbol", "")).strip()
    side = str(payload.get("side", "buy")).lower()
    quantity = float(payload.get("quantity", 0))
    if not symbol or quantity <= 0:
        raise HTTPException(status_code=400, detail="Valid symbol and quantity are required.")
    quote = _get_quote_for_symbol(symbol)
    if quote is None:
        raise HTTPException(status_code=404, detail=f"Market quote not available for {symbol}.")
    market_status = get_market_status()["markets"]
    provider_name = alias = "India" if symbol.endswith(".NS") else "United States" if symbol.upper() not in {pair for group in FOREX_PAIRS.values() for pair in group} else "Forex"
    if market_status.get(provider_name, {}).get("status") == "DISCONNECTED":
        raise HTTPException(status_code=409, detail="Market feed is disconnected; paper trading is disabled until data reconnects.")
    order = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "quantity": quantity,
        "price": quote["price"],
        "stop_loss": float(payload.get("stop_loss", quote["price"] * 0.97)),
        "target": float(payload.get("target", quote["price"] * 1.03)),
        "timestamp": _now_iso(),
        "status": "FILLED",
    }
    return {"status": "accepted", "order": order, "message": "Virtual paper order accepted using the latest available quote."}


@app.websocket("/ws/market")
async def market_websocket(websocket: WebSocket):
    await websocket.accept()
    subscribed_symbols: set[str] = set()
    try:
        await websocket.send_json({"type": "status", "payload": get_market_status(), "timestamp": _now_iso()})
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=15)
            except asyncio.TimeoutError:
                if not subscribed_symbols:
                    subscribed_symbols = {"RELIANCE.NS", "AAPL", "EUR/USD"}
                snapshot = {
                    "type": "market_snapshot",
                    "symbols": {},
                    "provider_status": get_market_status(),
                    "timestamp": _now_iso(),
                }
                for symbol in sorted(subscribed_symbols):
                    snapshot["symbols"][symbol] = market_data_service.market_snapshot(symbol)
                await websocket.send_json(snapshot)
                continue

            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON payload", "timestamp": _now_iso()})
                continue

            message_type = payload.get("type")
            if message_type == "subscribe":
                symbols = payload.get("symbols") or []
                subscribed_symbols = {str(symbol) for symbol in symbols}
                await websocket.send_json({"type": "subscription_ack", "symbols": sorted(subscribed_symbols), "timestamp": _now_iso()})
                continue
            if message_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": _now_iso()})
                continue
            if message_type == "status":
                await websocket.send_json({"type": "status", "payload": get_market_status(), "timestamp": _now_iso()})
                continue
            await websocket.send_json({"type": "error", "message": "Unsupported websocket message", "timestamp": _now_iso()})
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
