# QUANT-X
AI-powered multi-market research and paper-trading terminal.

## Development build
React + TypeScript + Vite frontend with KLineChart; FastAPI backend; provider status, quotes, historical candles, transparent technical signals, basic SMA backtest and SQLite virtual paper-order ledger. Markets: India, US equities and Forex.

## Setup
Backend:
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Windows activation: `venv\\Scripts\\activate`.

Frontend:
```bash
cd frontend
npm install
cp .env.example .env
npm run dev -- --host 0.0.0.0
```
Set VITE_API_URL to the backend URL. Provider keys must remain backend-only.

## Providers
Alpaca: ALPACA_API_KEY and ALPACA_SECRET_KEY (Basic feed may be IEX-only).
Twelve Data: TWELVE_DATA_API_KEY (plan quotas and display rights apply).
India: choose an authorized NSE/BSE data vendor and implement its documented adapter. India quote/history intentionally return 503 until configured; no brokerage connection is assumed.

Inject secrets into the backend environment/Codespaces secrets; never commit keys.

## Routes
GET /health, /api/providers, /api/markets
GET /api/quote/{market}/{symbol}
GET /api/history/{market}/{symbol}
GET /api/signals/{market}/{symbol}
POST /api/backtest
POST /api/paper/orders; GET /api/paper/orders; GET /api/paper/portfolio
GET /api/news (unconfigured until a provider is selected)

## Known limitations
Not yet a complete production trading system: no India vendor adapter, consolidated real-time US feed, unrestricted Forex stream, trained ML model, advanced strategy builder, exchange-grade backtest, live portfolio valuation, news sentiment, or broker execution. Paper orders are virtual only. Confirm provider exchange permissions, quotas, display and redistribution terms. Not financial advice.
