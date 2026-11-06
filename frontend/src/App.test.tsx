import { render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'

import App, { getApiBaseUrl } from './App'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)

    if (url.includes('/api/market-status')) {
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({
          status: 'DEGRADED',
          markets: {
            India: { status: 'DISCONNECTED', provider: 'Historical fallback', requires_subscription: true, required_credentials: ['UPSTOX_API_KEY'], notes: 'No creds', credentials_present: 0, timestamp: '2026-11-03T00:00:00Z' },
            'United States': { status: 'DISCONNECTED', provider: 'Historical fallback', requires_subscription: true, required_credentials: ['ALPACA_API_KEY'], notes: 'No creds', credentials_present: 0, timestamp: '2026-11-03T00:00:00Z' },
            Forex: { status: 'DISCONNECTED', provider: 'Historical fallback', requires_subscription: true, required_credentials: ['OANDA_API_KEY'], notes: 'No creds', credentials_present: 0, timestamp: '2026-11-03T00:00:00Z' },
          },
          warning: 'Using historical mode.',
        }),
      } as Response
    }

    if (url.includes('/api/market-list')) {
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({
          markets: [
            {
              category: 'India',
              items: [{ symbol: 'RELIANCE.NS', name: 'Reliance Industries', price: 2610.5, change_percent: 1.5, volume: 1200000, last_updated: '2026-11-03T12:00:00Z' }],
            },
            {
              category: 'United States',
              items: [{ symbol: 'AAPL', name: 'Apple', price: 201.18, change_percent: 0.8, volume: 9500000, last_updated: '2026-11-03T12:00:00Z' }],
            },
          ],
          provider_status: {},
          timestamp: '2026-11-03T12:00:00Z',
        }),
      } as Response
    }

    if (url.includes('/api/forex/dashboard')) {
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({
          watchlist: [{ pair: 'EUR/USD', price: 1.0876, daily_change_pct: 0.25 }],
          providers: [],
          session_status: {},
        }),
      } as Response
    }

    if (url.includes('/api/chart/')) {
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({
          candles: [
            { time: 1700000000, open: 100, high: 101, low: 99, close: 100.2, volume: 5000 },
            { time: 1700003600, open: 100.2, high: 102, low: 99.5, close: 101.3, volume: 5200 },
            { time: 1700007200, open: 101.3, high: 102.3, low: 100.6, close: 101.8, volume: 6100 },
          ],
        }),
      } as Response
    }

    return {
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({ detail: 'not found' }),
    } as Response
  }))
})

test('derives a backend URL for GitHub Codespaces forwards', () => {
  const original = window.location
  Object.defineProperty(window, 'location', {
    value: new URL('https://5173-abc123.app.github.dev'),
    writable: true,
  })

  expect(getApiBaseUrl()).toBe('https://8000-abc123.app.github.dev')

  Object.defineProperty(window, 'location', {
    value: original,
    writable: true,
  })
})

test('works for localhost development URLs', () => {
  const original = window.location
  Object.defineProperty(window, 'location', {
    value: new URL('http://localhost:5173'),
    writable: true,
  })

  expect(getApiBaseUrl()).toBe('http://localhost:8000')

  Object.defineProperty(window, 'location', {
    value: original,
    writable: true,
  })
})

test('renders the market dashboard shell', async () => {
  render(<App />)

  expect(await screen.findByText(/Market Dashboard/i)).toBeInTheDocument()
  expect(screen.getAllByText(/QUANT-X/i).length).toBeGreaterThan(0)
})
