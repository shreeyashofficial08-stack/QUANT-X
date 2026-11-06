# QUANT-X
AI-Powered Global Algorithmic Trading and Market Intelligence Platform

## Real-time market-data requirement

This project does not claim to provide verified real-time exchange data without the proper authorized vendor credentials and subscriptions.

The app now enforces honest provider status handling:
- `DISCONNECTED`: no live provider configured
- `DELAYED`: partial or delayed feed configured
- `AUTHORIZED`: credentials present, but live verification still required
- `LIVE`: only after a provider is actively connected and updating

To enable real-market integration, copy [.env.example](.env.example) to `.env` and add the credentials for an authorized provider such as:
- Upstox for Indian equities
- Alpaca for US equities / market data
- OANDA for FX data

No market should display a LIVE badge unless the corresponding provider connection is actually active and updating.
