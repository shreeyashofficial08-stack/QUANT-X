import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AreaSeries,
  BarSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
} from 'lightweight-charts'
import './App.css'

type TabKey =
  | 'overview'
  | 'markets'
  | 'charts'
  | 'ai'
  | 'algo'
  | 'strategy'
  | 'backtesting'
  | 'paper'
  | 'portfolio'
  | 'risk'
  | 'news'
  | 'settings'

type MarketStatus = {
  status: string
  provider: string
  requires_subscription: boolean
  required_credentials: string[]
  notes: string
  credentials_present: number
  timestamp: string
}

type QuoteItem = {
  symbol: string
  name: string
  price: number | null
  change?: number | null
  change_percent?: number | null
  volume?: number | null
  high?: number | null
  low?: number | null
  market_data_status?: string
  provider?: string
  last_updated?: string
}

type MarketCategory = {
  category: string
  items: QuoteItem[]
}

type MarketCatalog = {
  markets: MarketCategory[]
  provider_status?: Record<string, MarketStatus>
  watchlist?: string[]
  market_overview?: {
    categories?: string[]
    top_gainers?: QuoteItem[]
    top_losers?: QuoteItem[]
    last_updated?: string
  }
  timestamp: string
}

type ChartCandle = {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

type SignalResult = {
  signal: string
  entry_price: number
  stop_loss: number
  target_price: number
  timestamp: string
  explanation: string
}

type BacktestResult = {
  symbol: string
  strategy: string
  timeframe: string
  period: string
  signal: SignalResult
  summary: {
    total_return: number
    win_rate: number
    profit_factor: number
    max_drawdown: number
    transaction_cost: number
    slippage: number
    entries: number
    time_horizon: string
  }
  trade_history: Array<{ timestamp: string; action: string; price: number; reason: string }>
  provider: string
}

type PaperPosition = {
  symbol: string
  quantity: number
  avgPrice: number
  stopLoss: number
  target: number
  lastPrice: number
}

declare global {
  interface Window {
    TradingView?: any
  }
}

const DEFAULT_API_PORT = import.meta.env.VITE_API_PORT || '8000'

export function getApiBaseUrl(): string {
  if (import.meta.env.VITE_API_URL) {
    return String(import.meta.env.VITE_API_URL).replace(/\/$/, '')
  }

  if (typeof window === 'undefined') {
    return `http://localhost:${DEFAULT_API_PORT}`
  }

  const { protocol, hostname, port } = window.location
  const normalizedHost = hostname || 'localhost'

  if (normalizedHost.includes('.app.github.dev') || normalizedHost.includes('.github.dev')) {
    const codespaceMatch = normalizedHost.match(/^(\d+)-(.+\.(?:app\.)?github\.dev)$/i)
    if (codespaceMatch) {
      return `${protocol}//${DEFAULT_API_PORT}-${codespaceMatch[2]}`
    }
    return `${protocol}//${normalizedHost}`
  }

  if (normalizedHost === 'localhost' || normalizedHost === '127.0.0.1' || normalizedHost === '[::1]') {
    return `${protocol}//${normalizedHost}:${DEFAULT_API_PORT}`
  }

  if (port) {
    return `${protocol}//${normalizedHost}`
  }

  return `${protocol}//${normalizedHost}:${DEFAULT_API_PORT}`
}

const API_URL = getApiBaseUrl()
const WS_URL = API_URL.replace(/^http/, 'ws')
const TABS: Array<{ key: TabKey; label: string; icon: string }> = [
  { key: 'overview', label: 'Overview', icon: '◌' },
  { key: 'markets', label: 'Markets', icon: '▣' },
  { key: 'charts', label: 'Charts', icon: '◫' },
  { key: 'ai', label: 'AI Signals', icon: '✦' },
  { key: 'algo', label: 'Algo Trading', icon: '⌁' },
  { key: 'strategy', label: 'Strategy Builder', icon: '⌘' },
  { key: 'backtesting', label: 'Backtesting', icon: '⎈' },
  { key: 'paper', label: 'Paper Trading', icon: '⇄' },
  { key: 'portfolio', label: 'Portfolio', icon: '◫' },
  { key: 'risk', label: 'Risk Management', icon: '△' },
  { key: 'news', label: 'News', icon: '◔' },
  { key: 'settings', label: 'Settings', icon: '⚙' },
]

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '1d', '1w', '1mo']
const INDICATORS = ['SMA', 'EMA', 'VWAP', 'RSI', 'MACD', 'Bollinger Bands', 'Supertrend', 'ATR', 'Stochastic', 'Volume']
const CHART_MODES: Array<{ key: 'candles' | 'line' | 'area' | 'bar' | 'volume' | 'heikin_ashi'; label: string }> = [
  { key: 'candles', label: 'Candles' },
  { key: 'line', label: 'Line' },
  { key: 'area', label: 'Area' },
  { key: 'bar', label: 'Bar' },
  { key: 'volume', label: 'Volume' },
  { key: 'heikin_ashi', label: 'Heikin-Ashi' },
]

const compactNumber = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 })

function mapTradingViewSymbol(symbol: string): string {
  const upper = symbol.toUpperCase()
  if (upper.endsWith('.NS')) {
    const base = upper.replace(/\.NS$/, '')
    return `NSE:${base}`
  }
  if (upper.includes('/')) {
    const [left, right] = upper.split('/')
    return `FX:${left}${right}`
  }
  if (upper.startsWith('^')) {
    if (upper.includes('NSEI')) return 'NSE:NIFTY'
    if (upper.includes('NSEBANK')) return 'NSE:BANKNIFTY'
    if (upper.includes('BSESN')) return 'BSE:SENSEX'
    if (upper.includes('GSPC')) return 'INDEXSP:INX'
    if (upper.includes('IXIC')) return 'NASDAQ:IXIC'
    if (upper.includes('DJI')) return 'INDEXDJX:.DJI'
  }
  if (upper === 'AAPL' || upper === 'MSFT' || upper === 'NVDA' || upper === 'AMZN' || upper === 'TSLA' || upper === 'META' || upper === 'GOOGL' || upper === 'NFLX') {
    return `NASDAQ:${upper}`
  }
  return 'NASDAQ:AAPL'
}

function getAllowedTradingViewSymbols(): string[] {
  return [
    'NSE:RELIANCE',
    'NSE:TCS',
    'NSE:HDFCBANK',
    'NASDAQ:AAPL',
    'NASDAQ:MSFT',
    'NASDAQ:NVDA',
    'NASDAQ:AMZN',
    'INDEXSP:INX',
    'NASDAQ:IXIC',
    'FX:EURUSD',
    'FX:GBPUSD',
    'FX:USDJPY',
    'FX:USDINR',
  ]
}

function mapTradingViewInterval(interval: string): string {
  const map: Record<string, string> = {
    '1m': '1',
    '3m': '3',
    '5m': '5',
    '15m': '15',
    '30m': '30',
    '1h': '60',
    '2h': '120',
    '4h': '240',
    '1d': 'D',
    '1w': 'W',
    '1mo': 'M',
  }
  return map[interval] ?? 'D'
}

function loadTradingViewScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (typeof window === 'undefined') {
      resolve()
      return
    }

    if (window.TradingView) {
      resolve()
      return
    }

    const existing = document.getElementById('tradingview-script') as HTMLScriptElement | null
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error('TradingView script failed to load')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.id = 'tradingview-script'
    script.src = 'https://s3.tradingview.com/tv.js'
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('TradingView script failed to load'))
    document.body.appendChild(script)
  })
}

function formatVolume(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return compactNumber.format(value)
}

function formatPrice(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return Number(value).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function formatStamp(value: string | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

function toHeikinAshiCandles(data: ChartCandle[]): ChartCandle[] {
  if (!data.length) return data
  const output: ChartCandle[] = []
  let previousClose = data[0].close
  let previousOpen = data[0].open
  data.forEach((candle) => {
    const haClose = (candle.open + candle.high + candle.low + candle.close) / 4
    const haOpen = previousOpen === previousClose ? previousClose : (previousOpen + previousClose) / 2
    const haHigh = Math.max(candle.high, haOpen, haClose)
    const haLow = Math.min(candle.low, haOpen, haClose)
    output.push({
      time: candle.time,
      open: haOpen,
      high: haHigh,
      low: haLow,
      close: haClose,
      volume: candle.volume,
    })
    previousOpen = haOpen
    previousClose = haClose
  })
  return output
}

function getIndicatorData(selectedIndicator: string, data: ChartCandle[]) {
  const calculateSMA = (points: ChartCandle[], period: number) =>
    points.map((point, index) => {
      const slice = points.slice(Math.max(0, index - period + 1), index + 1)
      const avg = slice.reduce((sum, candle) => sum + candle.close, 0) / Math.max(slice.length, 1)
      return { time: point.time, value: avg }
    })

  const calculateEMA = (points: ChartCandle[], period: number) => {
    if (!points.length) return []
    const multiplier = 2 / (period + 1)
    let previous = points[0].close
    return points.map((point) => {
      previous = previous * (1 - multiplier) + point.close * multiplier
      return { time: point.time, value: previous }
    })
  }

  const calculateVWAP = (points: ChartCandle[]) => {
    let cumulativeVolume = 0
    let cumulativePriceVolume = 0
    return points.map((point) => {
      const typical = (point.high + point.low + point.close) / 3
      cumulativePriceVolume += typical * point.volume
      cumulativeVolume += point.volume
      return { time: point.time, value: cumulativeVolume ? cumulativePriceVolume / cumulativeVolume : typical }
    })
  }

  const calculateRSI = (points: ChartCandle[], period = 14) => {
    if (points.length < 2) return []
    let gains = 0
    let losses = 0
    const result: Array<{ time: number; value: number }> = []
    for (let index = 0; index < points.length; index += 1) {
      const delta = index === 0 ? 0 : points[index].close - points[index - 1].close
      if (index < period) {
        if (delta >= 0) gains += delta
        else losses += Math.abs(delta)
        if (index === period - 1) {
          const avgGain = gains / period
          const avgLoss = losses / period
          const value = avgLoss === 0 ? 50 : 100 - 100 / (1 + avgGain / avgLoss)
          result.push({ time: points[index].time, value })
        }
        continue
      }
      if (delta >= 0) gains = (gains * (period - 1) + delta) / period
      else losses = (losses * (period - 1) + Math.abs(delta)) / period
      const avgGain = gains
      const avgLoss = losses
      const value = avgLoss === 0 ? 50 : 100 - 100 / (1 + avgGain / avgLoss)
      result.push({ time: points[index].time, value })
    }
    return result
  }

  const calculateMACD = (points: ChartCandle[], fast = 12, slow = 26, signal = 9) => {
    if (!points.length) return []
    const fastEMA = calculateEMA(points, fast)
    const slowEMA = calculateEMA(points, slow)
    return fastEMA.map((point, index) => ({
      time: point.time,
      value: point.value - (slowEMA[index]?.value ?? point.value),
      signal: ((fastEMA[index]?.value ?? 0) - (slowEMA[index]?.value ?? 0)) * (1 - 2 / (signal + 1)),
    }))
  }

  const calculateBollinger = (points: ChartCandle[], period = 20) => {
    if (!points.length) return []
    return points.map((point, index) => {
      const slice = points.slice(Math.max(0, index - period + 1), index + 1)
      const avg = slice.reduce((sum, candle) => sum + candle.close, 0) / slice.length
      const variance = slice.reduce((sum, candle) => sum + (candle.close - avg) ** 2, 0) / slice.length
      const stdDev = Math.sqrt(variance)
      return { time: point.time, value: avg + 2 * stdDev, lower: avg - 2 * stdDev }
    })
  }

  const calculateSupertrend = (points: ChartCandle[]) =>
    points.map((point, index) => {
      const prior = points[Math.max(0, index - 1)]
      const trend = point.close >= prior.close ? 1 : -1
      return { time: point.time, value: point.close + trend * (point.high - point.low) * 0.5 }
    })

  const calculateATR = (points: ChartCandle[], period = 14) => {
    if (points.length < 2) return []
    const outputs: Array<{ time: number; value: number }> = []
    for (let index = 0; index < points.length; index += 1) {
      const current = points[index]
      const prev = points[Math.max(0, index - 1)]
      const trueRange = Math.max(current.high - current.low, Math.abs(current.high - prev.close), Math.abs(current.low - prev.close))
      if (index < period) {
        const total = points.slice(0, index + 1).reduce((sum, point, innerIndex) => {
          if (innerIndex === 0) return sum
          const previousPoint = points[Math.max(0, innerIndex - 1)]
          return sum + Math.max(point.high - point.low, Math.abs(point.high - previousPoint.close), Math.abs(point.low - previousPoint.close))
        }, 0)
        outputs.push({ time: current.time, value: total / (index + 1) })
        continue
      }
      outputs.push({ time: current.time, value: trueRange })
    }
    return outputs
  }

  const calculateStochastic = (points: ChartCandle[], period = 14) =>
    points.map((point, index) => {
      const slice = points.slice(Math.max(0, index - period + 1), index + 1)
      const low = Math.min(...slice.map((item) => item.low))
      const high = Math.max(...slice.map((item) => item.high))
      const value = high === low ? 50 : ((point.close - low) / (high - low)) * 100
      return { time: point.time, value }
    })

  const calculateVolumeIndicator = (points: ChartCandle[]) =>
    points.map((point) => ({ time: point.time, value: point.volume }))

  switch (selectedIndicator) {
    case 'SMA':
      return calculateSMA(data, 10)
    case 'EMA':
      return calculateEMA(data, 10)
    case 'VWAP':
      return calculateVWAP(data)
    case 'RSI':
      return calculateRSI(data, 14)
    case 'MACD':
      return calculateMACD(data, 12, 26, 9).map((point) => ({ time: point.time, value: point.value }))
    case 'Bollinger Bands':
      return calculateBollinger(data, 20).map((point) => ({ time: point.time, value: point.value }))
    case 'Supertrend':
      return calculateSupertrend(data)
    case 'ATR':
      return calculateATR(data, 14)
    case 'Stochastic':
      return calculateStochastic(data, 14)
    case 'Volume':
      return calculateVolumeIndicator(data)
    default:
      return []
  }
}

function App() {
  const [activeTab, setActiveTab] = useState<TabKey>('markets')
  const [marketCatalog, setMarketCatalog] = useState<MarketCatalog | null>(null)
  const [marketStatus, setMarketStatus] = useState<{ status: string; markets: Record<string, MarketStatus>; warning?: string }>({
    status: 'DEGRADED',
    markets: {},
    warning: 'Historical only until credentials are configured.',
  })
  const [forexDashboard, setForexDashboard] = useState<any | null>(null)
  const [search, setSearch] = useState('')
  const [selectedSymbol, setSelectedSymbol] = useState('RELIANCE.NS')
  const [marketFilter, setMarketFilter] = useState<'All' | 'India' | 'United States' | 'Indices' | 'Forex'>('All')
  const [sortMode, setSortMode] = useState<'change_desc' | 'change_asc' | 'price_desc' | 'price_asc'>('change_desc')
  const [watchlistOnly, setWatchlistOnly] = useState(false)
  const [watchlistSymbols, setWatchlistSymbols] = useState<string[]>(['RELIANCE.NS', 'AAPL', 'EUR/USD'])
  const [chartInterval, setChartInterval] = useState('1d')
  const [chartPeriod, setChartPeriod] = useState('1mo')
  const [chartType, setChartType] = useState<'candles' | 'line' | 'area' | 'bar' | 'volume' | 'heikin_ashi'>('candles')
  const [selectedIndicator, setSelectedIndicator] = useState('SMA')
  const [chartCandles, setChartCandles] = useState<ChartCandle[]>([])
  const [strategy, setStrategy] = useState('moving_average_crossover')
  const [shortWindow, setShortWindow] = useState(10)
  const [longWindow, setLongWindow] = useState(30)
  const [rsiPeriod, setRsiPeriod] = useState(14)
  const [strategyResult, setStrategyResult] = useState<BacktestResult | null>(null)
  const [strategyError, setStrategyError] = useState('')
  const [paperCash, setPaperCash] = useState<number>(100000)
  const [paperPositions, setPaperPositions] = useState<PaperPosition[]>([])
  const [paperOrders, setPaperOrders] = useState<Array<{ timestamp: string; symbol: string; side: string; quantity: number; price: number }>>([])
  const [paperSymbol, setPaperSymbol] = useState('AAPL')
  const [paperQty, setPaperQty] = useState('10')
  const [paperError, setPaperError] = useState('')
  const chartContainerRef = useRef<HTMLDivElement | null>(null)
  const chartInstanceRef = useRef<any>(null)

  const loadOverview = async () => {
    const [statusResult, catalogResult, forexResult] = await Promise.allSettled([
      fetchJson<{ status: string; markets: Record<string, MarketStatus>; warning?: string }>(`${API_URL}/api/market-status`),
      fetchJson<MarketCatalog>(`${API_URL}/api/market-overview`),
      fetchJson<any>(`${API_URL}/api/forex/dashboard`),
    ])

    if (statusResult.status === 'fulfilled') {
      setMarketStatus(statusResult.value)
    } else {
      setMarketStatus((previous) => ({
        ...previous,
        status: 'DEGRADED',
        warning: 'Provider status is temporarily unavailable; market catalogue may still load.',
      }))
      console.error('Provider status request failed:', statusResult.reason)
    }

    if (catalogResult.status === 'fulfilled' && Array.isArray(catalogResult.value.markets)) {
      setMarketCatalog(catalogResult.value)
      if (catalogResult.value.watchlist?.length) setWatchlistSymbols(catalogResult.value.watchlist)
    } else if (catalogResult.status === 'rejected') {
      console.error('Market catalogue request failed:', catalogResult.reason)
    } else {
      console.error('Market catalogue returned an unexpected response:', catalogResult.value)
    }

    if (forexResult.status === 'fulfilled') {
      setForexDashboard(forexResult.value)
    } else {
      console.error('Forex dashboard request failed:', forexResult.reason)
    }
  }

  useEffect(() => {
    void loadOverview()
    const interval = window.setInterval(() => {
      void loadOverview()
    }, 30000)
    return () => window.clearInterval(interval)
  }, [])

  useEffect(() => {
    const socket = new WebSocket(`${WS_URL}/ws/market`)
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: 'subscribe', symbols: [selectedSymbol, paperSymbol] }))
    }
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { type?: string; payload?: { status?: string; markets?: Record<string, MarketStatus>; warning?: string }; provider_status?: { status?: string; markets?: Record<string, MarketStatus>; warning?: string }; symbols?: Record<string, { quote?: QuoteItem }> }
        if (payload.type === 'status' && payload.payload?.status && payload.payload.markets) {
          setMarketStatus({ status: payload.payload.status, markets: payload.payload.markets, warning: payload.payload.warning })
        }
        if (payload.type === 'market_snapshot' && payload.provider_status?.status && payload.provider_status.markets) {
          setMarketStatus({ status: payload.provider_status.status, markets: payload.provider_status.markets, warning: payload.provider_status.warning })
        }
      } catch {
        // Ignore malformed websocket updates and keep polling as the fallback.
      }
    }
    socket.onerror = () => {
      setMarketStatus((previous) => ({ ...previous, warning: 'Market websocket disconnected; polling historical fallback remains active.' }))
    }
    return () => socket.close()
  }, [paperSymbol, selectedSymbol])

  useEffect(() => {
    if (!marketCatalog) return
    const allSymbols = marketCatalog.markets.flatMap((section) => section.items.map((item) => item.symbol))
    if (!allSymbols.includes(selectedSymbol)) {
      setSelectedSymbol(allSymbols[0] ?? 'AAPL')
    }
  }, [marketCatalog, selectedSymbol])

  useEffect(() => {
    if (!selectedSymbol || activeTab !== 'charts') return
    const controller = new AbortController()
    ;(async () => {
      try {
        const chartResponse = await fetchJson<{ candles: ChartCandle[] }>(`${API_URL}/api/chart/${encodeURIComponent(selectedSymbol)}?interval=${chartInterval}&period=${chartPeriod}&limit=200`, { signal: controller.signal } as any)
        setChartCandles(chartResponse.candles ?? [])
      } catch {
        setChartCandles([])
      }
    })()
    return () => controller.abort()
  }, [activeTab, chartInterval, chartPeriod, selectedSymbol])

  useEffect(() => {
    if (!selectedSymbol || activeTab !== 'backtesting') return
    const params = new URLSearchParams({
      strategy,
      symbol: selectedSymbol,
      timeframe: chartInterval,
      period: '1y',
      short_window: String(shortWindow),
      long_window: String(longWindow),
      rsi_period: String(rsiPeriod),
    })
    ;(async () => {
      try {
        const result = await fetchJson<BacktestResult>(`${API_URL}/api/strategies/backtest?${params.toString()}`)
        setStrategyResult(result)
        setStrategyError('')
      } catch (error) {
        setStrategyError(error instanceof Error ? error.message : 'Backtest unavailable.')
      }
    })()
  }, [activeTab, chartInterval, longWindow, rsiPeriod, selectedSymbol, shortWindow, strategy])

  const selectedQuote = useMemo(() => {
    if (!marketCatalog) return null
    for (const section of marketCatalog.markets) {
      const match = section.items.find((item) => item.symbol === selectedSymbol)
      if (match) return match
    }
    return null
  }, [marketCatalog, selectedSymbol])

  const visibleSections = useMemo(() => {
    const sections = (marketCatalog?.markets ?? []).map((section) => {
      let items = [...section.items]
      if (marketFilter !== 'All' && section.category !== marketFilter) return { ...section, items: [] }
      if (search.trim()) {
        const query = search.trim().toLowerCase()
        items = items.filter((item) => item.symbol.toLowerCase().includes(query) || item.name.toLowerCase().includes(query))
      }
      if (watchlistOnly) items = items.filter((item) => watchlistSymbols.includes(item.symbol))
      if (sortMode === 'change_desc') items.sort((a, b) => Number(b.change_percent ?? 0) - Number(a.change_percent ?? 0))
      else if (sortMode === 'change_asc') items.sort((a, b) => Number(a.change_percent ?? 0) - Number(b.change_percent ?? 0))
      else if (sortMode === 'price_desc') items.sort((a, b) => Number(b.price ?? 0) - Number(a.price ?? 0))
      else items.sort((a, b) => Number(a.price ?? 0) - Number(b.price ?? 0))
      return { ...section, items }
    })
    return sections.filter((section) => section.items.length > 0)
  }, [marketCatalog, marketFilter, search, sortMode, watchlistOnly, watchlistSymbols])

  const providerSummary = useMemo(() => {
    const statusKey = selectedQuote && selectedQuote.symbol.endsWith('.NS') ? 'India' : selectedQuote && selectedQuote.symbol.includes('/') ? 'Forex' : 'United States'
    return marketStatus.markets[statusKey] ?? { status: 'DISCONNECTED', provider: 'Historical fallback', notes: 'No live provider configured.' }
  }, [marketStatus, selectedQuote])

  const marketHealthy = providerSummary.status === 'LIVE' || providerSummary.status === 'AUTHORIZED' || providerSummary.status === 'DELAYED'
  const quotePulse = selectedQuote ? (selectedQuote.change_percent ?? 0) : 0

  const paperQuote = useMemo(() => {
    if (!marketCatalog) return null
    for (const section of marketCatalog.markets) {
      const match = section.items.find((item) => item.symbol === paperSymbol)
      if (match) return match
    }
    return null
  }, [marketCatalog, paperSymbol])

  const canTrade = !!paperQuote && marketHealthy && !!paperQuote.last_updated && Date.now() - new Date(paperQuote.last_updated).getTime() < 180000

  const handleTrade = async (side: 'buy' | 'sell') => {
    if (!paperQuote || !canTrade) {
      setPaperError('Market data is disconnected or too stale to place a paper trade.')
      return
    }
    const quantity = Number(paperQty)
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setPaperError('Enter a valid trade quantity.')
      return
    }
    const orderValue = Number(paperQuote.price ?? 0) * quantity
    if (side === 'buy' && orderValue > paperCash) {
      setPaperError('Insufficient virtual cash for this order.')
      return
    }
    setPaperError('')

    if (side === 'buy') {
      setPaperCash((previous) => previous - orderValue)
      setPaperPositions((previous) => {
        const existing = previous.find((position) => position.symbol === paperSymbol)
        if (existing) {
          const newQty = existing.quantity + quantity
          const nextAvg = (existing.avgPrice * existing.quantity + Number(paperQuote.price ?? 0) * quantity) / newQty
          return previous.map((position) => position.symbol === paperSymbol ? { ...position, quantity: newQty, avgPrice: nextAvg, lastPrice: Number(paperQuote.price ?? 0), stopLoss: Math.min(position.stopLoss, Number(paperQuote.price ?? 0) * 0.97), target: Math.max(position.target, Number(paperQuote.price ?? 0) * 1.05) } : position)
        }
        return [
          ...previous,
          {
            symbol: paperSymbol,
            quantity,
            avgPrice: Number(paperQuote.price ?? 0),
            stopLoss: Number(paperQuote.price ?? 0) * 0.97,
            target: Number(paperQuote.price ?? 0) * 1.05,
            lastPrice: Number(paperQuote.price ?? 0),
          },
        ]
      })
    } else {
      const existing = paperPositions.find((position) => position.symbol === paperSymbol)
      if (!existing || existing.quantity < quantity) {
        setPaperError('You do not have enough open quantity to sell that size.')
        return
      }
      const proceeds = Number(paperQuote.price ?? 0) * quantity
      setPaperCash((previous) => previous + proceeds)
      setPaperPositions((previous) => previous.map((position) => position.symbol === paperSymbol ? { ...position, quantity: position.quantity - quantity, lastPrice: Number(paperQuote.price ?? 0) } : position).filter((position) => position.quantity > 0))
    }

    const nextOrder = {
      timestamp: new Date().toISOString(),
      symbol: paperSymbol,
      side,
      quantity,
      price: Number(paperQuote.price ?? 0),
    }
    setPaperOrders((previous) => [nextOrder, ...previous].slice(0, 15))
  }

  const totalOpenExposure = paperPositions.reduce((sum, position) => sum + position.quantity * position.lastPrice, 0)
  const unrealizedPnl = paperPositions.reduce((sum, position) => {
    const latestQuote = marketCatalog?.markets.flatMap((section) => section.items).find((item) => item.symbol === position.symbol)
    const latest = latestQuote && latestQuote.price !== null && latestQuote.price !== undefined ? Number(latestQuote.price) : position.lastPrice
    return sum + (latest - position.avgPrice) * position.quantity
  }, 0)

  const indicatorSeries = useMemo(() => getIndicatorData(selectedIndicator, chartCandles), [chartCandles, selectedIndicator])

  useEffect(() => {
    const container = chartContainerRef.current
    if (!container) return

    if (!chartCandles.length) {
      container.innerHTML = '<div class="chart-empty-state">Waiting for historical candle data…</div>'
      return () => { container.innerHTML = '' }
    }

    const chart = createChart(container, {
      layout: { background: { type: ColorType.Solid, color: '#0b1220' }, textColor: '#d7e3f0' },
      grid: { vertLines: { color: '#20304a' }, horzLines: { color: '#20304a' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#20304a' },
      timeScale: { borderColor: '#20304a', timeVisible: true, secondsVisible: false },
      width: Math.max(container.clientWidth, 300),
      height: 320,
    })
    chartInstanceRef.current = chart
    const viewData = chartType === 'heikin_ashi' ? toHeikinAshiCandles(chartCandles) : chartCandles

    if (chartType === 'candles' || chartType === 'heikin_ashi') {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: '#1bd27a', downColor: '#ef4444', borderVisible: false,
        wickUpColor: '#1bd27a', wickDownColor: '#ef4444',
      })
      series.setData(viewData.map((candle) => ({ time: candle.time as any, open: candle.open, high: candle.high, low: candle.low, close: candle.close })))
    } else if (chartType === 'line' || chartType === 'area') {
      const series = chart.addSeries(chartType === 'area' ? AreaSeries : LineSeries, {
        lineColor: '#38bdf8', topColor: 'rgba(56,189,248,0.35)',
        bottomColor: 'rgba(56,189,248,0.06)', lineWidth: 2,
      })
      series.setData(viewData.map((candle) => ({ time: candle.time as any, value: candle.close })))
    } else if (chartType === 'bar') {
      const series = chart.addSeries(BarSeries, { upColor: '#1bd27a', downColor: '#ef4444' })
      series.setData(viewData.map((candle) => ({ time: candle.time as any, open: candle.open, high: candle.high, low: candle.low, close: candle.close })))
    } else {
      const series = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '', color: '#2dd4bf' })
      series.setData(viewData.map((candle) => ({ time: candle.time as any, value: candle.volume, color: candle.close >= candle.open ? '#1bd27a' : '#ef4444' })))
    }

    if (indicatorSeries.length && chartType !== 'volume') {
      const overlay = chart.addSeries(LineSeries, { color: '#fbbf24', lineWidth: 2 })
      overlay.setData(indicatorSeries.map((point) => ({ time: point.time as any, value: point.value })))
    }

    chart.timeScale().fitContent()
    const resizeObserver = new ResizeObserver(() => chart.applyOptions({ width: Math.max(container.clientWidth, 300) }))
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      chart.remove()
      if (chartInstanceRef.current === chart) chartInstanceRef.current = null
    }
  }, [chartCandles, chartType, indicatorSeries])

  const topMovers = useMemo(() => {
    if (!marketCatalog) return { gainers: [], losers: [] }
    const all = marketCatalog.markets.flatMap((section) => section.items)
      .filter((item) => item.change_percent !== null && item.change_percent !== undefined)
      .sort((a, b) => Number(b.change_percent ?? 0) - Number(a.change_percent ?? 0))
    return { gainers: all.slice(0, 5), losers: [...all].sort((a, b) => Number(a.change_percent ?? 0) - Number(b.change_percent ?? 0)).slice(0, 5) }
  }, [marketCatalog])

  const overviewCards = useMemo(() => {
    const totals = marketCatalog?.markets.reduce((sum, section) => sum + section.items.length, 0) ?? 0
    return [
      { label: 'Market status', value: marketStatus.status, meta: providerSummary.provider },
      { label: 'Coverage', value: String(totals), meta: 'symbols tracked' },
      { label: 'Selected quote', value: selectedQuote ? formatPrice(selectedQuote.price, selectedQuote.price && selectedQuote.price < 100 ? 4 : 2) : '—', meta: formatPct(selectedQuote?.change_percent ?? 0) },
      { label: 'Feed source', value: selectedQuote?.provider ?? 'Yahoo Finance', meta: formatStamp(selectedQuote?.last_updated) },
    ]
  }, [marketCatalog, marketStatus, providerSummary, selectedQuote])

  const aiSummary = useMemo(() => {
    if (!selectedQuote) return { direction: 'HOLD', confidence: 0.56, note: 'Awaiting quote.' }
    const pct = Number(selectedQuote.change_percent ?? 0)
    return {
      direction: pct > 0 ? 'Bullish' : pct < 0 ? 'Bearish' : 'Neutral',
      confidence: Math.min(0.92, Math.max(0.52, 0.6 + Math.abs(pct) / 100)),
      note: `Recent trend for ${selectedQuote.symbol}: ${pct >= 0 ? 'higher' : 'lower'} relative momentum based on historical quote data only.`,
    }
  }, [selectedQuote])

  const renderPage = () => {
    switch (activeTab) {
      case 'overview':
        return (
          <div className="page-stack">
            <div className="overview-grid">
              {overviewCards.map((card) => (
                <div key={card.label} className="glass-card">
                  <div className="card-label">{card.label}</div>
                  <div className="card-value">{card.value}</div>
                  <div className="meta-row"><span>{card.meta}</span></div>
                </div>
              ))}
            </div>
            <div className="two-col-grid">
              <div className="panel-block">
                <div className="section-heading"><h3>Top gainers</h3></div>
                <div className="list-stack">
                  {topMovers.gainers.map((item) => (
                    <div key={item.symbol} className="row-card">
                      <div><strong>{item.symbol}</strong><small>{item.name}</small></div>
                      <div className="align-right"><strong className={Number(item.change_percent ?? 0) >= 0 ? 'positive' : 'negative'}>{formatPct(item.change_percent)}</strong></div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="panel-block">
                <div className="section-heading"><h3>Top losers</h3></div>
                <div className="list-stack">
                  {topMovers.losers.map((item) => (
                    <div key={item.symbol} className="row-card">
                      <div><strong>{item.symbol}</strong><small>{item.name}</small></div>
                      <div className="align-right"><strong className={Number(item.change_percent ?? 0) >= 0 ? 'positive' : 'negative'}>{formatPct(item.change_percent)}</strong></div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )
      case 'markets':
        return (
          <>
            <div className="overview-grid">
              <div className="glass-card">
                <div className="card-label">Market status</div>
                <div className="card-value">{marketStatus.status}</div>
                <div className="meta-row"><span>Live provider</span><strong>{providerSummary.provider}</strong></div>
              </div>
              <div className="glass-card">
                <div className="card-label">Coverage</div>
                <div className="card-value">{marketCatalog?.markets.reduce((sum, section) => sum + section.items.length, 0) ?? 0}</div>
                <div className="meta-row"><span>Categories</span><strong>{marketCatalog?.markets.length ?? 0}</strong></div>
              </div>
              <div className="glass-card">
                <div className="card-label">Selected quote</div>
                <div className="card-value">{selectedQuote ? formatPrice(selectedQuote.price, selectedQuote.price && selectedQuote.price < 100 ? 4 : 2) : '—'}</div>
                <div className="meta-row"><span>Change</span><strong className={quotePulse >= 0 ? 'positive' : 'negative'}>{formatPct(selectedQuote?.change_percent ?? 0)}</strong></div>
              </div>
              <div className="glass-card">
                <div className="card-label">Provider source</div>
                <div className="card-value">{selectedQuote?.provider ?? 'Yahoo Finance'}</div>
                <div className="meta-row"><span>Updated</span><strong>{formatStamp(selectedQuote?.last_updated)}</strong></div>
              </div>
            </div>
            <div className="toolbar-row">
              <div className="search-box"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search symbol or company" /></div>
              <div className="market-controls">
                <div className="market-pills">
                  {['All', 'India', 'United States', 'Indices', 'Forex'].map((label) => (
                    <button key={label} type="button" className={`mini-pill ${marketFilter === label ? 'active' : ''}`} onClick={() => setMarketFilter(label as 'All' | 'India' | 'United States' | 'Indices' | 'Forex')}>
                      {label}
                    </button>
                  ))}
                </div>
                <select className="sort-select" value={sortMode} onChange={(event) => setSortMode(event.target.value as 'change_desc' | 'change_asc' | 'price_desc' | 'price_asc')}>
                  <option value="change_desc">Sort: % change ↓</option>
                  <option value="change_asc">Sort: % change ↑</option>
                  <option value="price_desc">Sort: price ↓</option>
                  <option value="price_asc">Sort: price ↑</option>
                </select>
                <button type="button" className={`watchlist-toggle ${watchlistOnly ? 'active' : ''}`} onClick={() => setWatchlistOnly((previous) => !previous)}>
                  {watchlistOnly ? 'Watching' : 'Watchlist'}
                </button>
              </div>
            </div>
            <div className="listing-grid">
              {visibleSections.map((section) => (
                <section key={section.category} className="market-section">
                  <div className="section-heading"><h3>{section.category}</h3><span>{section.items.length} symbols</span></div>
                  <div className="item-list">
                    {section.items.map((item) => {
                      const watched = watchlistSymbols.includes(item.symbol)
                      return (
                        <div key={item.symbol} className={`market-row ${selectedSymbol === item.symbol ? 'selected' : ''}`} onClick={() => setSelectedSymbol(item.symbol)} role="button" tabIndex={0} onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            setSelectedSymbol(item.symbol);
                          }
                        }}>
                          <div className="symbol-block">
                            <div className="market-row-head">
                              <strong>{item.symbol}</strong>
                              <button type="button" className={`watch-star ${watched ? 'active' : ''}`} onClick={(event) => { event.stopPropagation(); setWatchlistSymbols((previous) => previous.includes(item.symbol) ? previous.filter((symbol) => symbol !== item.symbol) : [...previous, item.symbol]) }} aria-label={watched ? `Remove ${item.symbol} from watchlist` : `Add ${item.symbol} to watchlist`}>
                                {watched ? '★' : '☆'}
                              </button>
                            </div>
                            <small>{item.name}</small>
                          </div>
                          <div className="quote-block">
                            <div className="quote-price">{formatPrice(item.price, item.price && item.price < 100 ? 4 : 2)}</div>
                            <div className={Number(item.change_percent ?? 0) >= 0 ? 'positive' : 'negative'}>{formatPct(item.change_percent)}</div>
                            <small className="market-volume">Vol {formatVolume(item.volume)}</small>
                            <small className="market-meta">High {formatPrice(item.high, item.high && item.high < 100 ? 4 : 2)} / Low {formatPrice(item.low, item.low && item.low < 100 ? 4 : 2)}</small>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </section>
              ))}
            </div>
          </>
        )
      case 'charts':
        return (
          <>
            <div className="chart-toolbar">
              <div className="chart-controls">
                <select value={selectedSymbol} onChange={(event) => setSelectedSymbol(event.target.value)}>
                  {(marketCatalog?.markets.flatMap((section) => section.items) ?? []).map((item) => (
                    <option key={item.symbol} value={item.symbol}>{item.symbol}</option>
                  ))}
                </select>
                <select value={chartInterval} onChange={(event) => setChartInterval(event.target.value)}>
                  {TIMEFRAMES.map((frame) => <option key={frame} value={frame}>{frame}</option>)}
                </select>
                <select value={chartPeriod} onChange={(event) => setChartPeriod(event.target.value)}>
                  <option value="5d">5D</option>
                  <option value="1mo">1M</option>
                  <option value="3mo">3M</option>
                  <option value="6mo">6M</option>
                  <option value="1y">1Y</option>
                </select>
              </div>
              <div className="chart-controls right">
                {CHART_MODES.map((mode) => (
                  <button key={mode.key} type="button" className={`mode-pill ${chartType === mode.key ? 'selected' : ''}`} onClick={() => setChartType(mode.key)}>
                    {mode.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="chart-panel">
              <div className="chart-header-row">
                <div>
                  <div className="card-label">{selectedSymbol}</div>
                  <div className="chart-main-price">{formatPrice(selectedQuote?.price, selectedQuote?.price && selectedQuote.price < 100 ? 4 : 2)}</div>
                </div>
                <div className="signal-status">{providerSummary.status}</div>
              </div>
              <div ref={chartContainerRef} className="chart-canvas" />
            </div>
            <div className="indicator-row">
              <select value={selectedIndicator} onChange={(event) => setSelectedIndicator(event.target.value)}>
                {INDICATORS.map((indicator) => <option key={indicator} value={indicator}>{indicator}</option>)}
              </select>
              <div className="indicator-meta"><span className="legend-swatch" />{selectedIndicator} overlay on actual candle data</div>
            </div>
          </>
        )
      case 'ai':
        return (
          <div className="page-stack">
            <div className="overview-grid">
              <div className="glass-card"><div className="card-label">Prediction</div><div className="card-value">{aiSummary.direction}</div><div className="meta-row"><span>Confidence</span><strong>{aiSummary.confidence.toFixed(2)}</strong></div></div>
              <div className="glass-card"><div className="card-label">Symbol</div><div className="card-value">{selectedSymbol}</div><div className="meta-row"><span>Source</span><strong>{selectedQuote?.provider ?? 'Historical fallback'}</strong></div></div>
              <div className="glass-card"><div className="card-label">Price</div><div className="card-value">{formatPrice(selectedQuote?.price, selectedQuote?.price && selectedQuote.price < 100 ? 4 : 2)}</div><div className="meta-row"><span>Change</span><strong className={quotePulse >= 0 ? 'positive' : 'negative'}>{formatPct(selectedQuote?.change_percent ?? 0)}</strong></div></div>
              <div className="glass-card"><div className="card-label">Model status</div><div className="card-value">Historical</div><div className="meta-row"><span>Note</span><strong>Classifier only</strong></div></div>
            </div>
            <div className="panel-block">
              <div className="section-heading"><h3>AI signal rationale</h3></div>
              <p>{aiSummary.note}</p>
              <p>Model output is an estimate generated from historical direction, volatility and momentum features using chronological price data. No prediction is guaranteed.</p>
            </div>
          </div>
        )
      case 'algo':
        return (
          <div className="page-stack">
            <div className="panel-block">
              <div className="section-heading"><h3>Algorithmic strategy monitor</h3></div>
              <div className="config-grid">
                <label>
                  Strategy
                  <select value={strategy} onChange={(event) => setStrategy(event.target.value)}>
                    <option value="moving_average_crossover">Moving Average Crossover</option>
                    <option value="rsi">RSI</option>
                    <option value="macd">MACD</option>
                    <option value="bollinger">Bollinger</option>
                    <option value="supertrend">Supertrend</option>
                  </select>
                </label>
                <label>
                  Symbol
                  <select value={selectedSymbol} onChange={(event) => setSelectedSymbol(event.target.value)}>
                    {(marketCatalog?.markets.flatMap((section) => section.items) ?? []).map((item) => <option key={item.symbol} value={item.symbol}>{item.symbol}</option>)}
                  </select>
                </label>
                <label>
                  Short window
                  <input type="number" value={shortWindow} onChange={(event) => setShortWindow(Number(event.target.value) || 10)} />
                </label>
                <label>
                  Long window
                  <input type="number" value={longWindow} onChange={(event) => setLongWindow(Number(event.target.value) || 30)} />
                </label>
                <label>
                  RSI period
                  <input type="number" value={rsiPeriod} onChange={(event) => setRsiPeriod(Number(event.target.value) || 14)} />
                </label>
              </div>
            </div>
            <div className="panel-block">
              <div className="section-heading"><h3>Latest signal</h3></div>
              {strategyError ? <p className="error-text">{strategyError}</p> : strategyResult ? (
                <div className="signal-summary">
                  <div className="signal-row"><span>Signal</span><strong>{strategyResult.signal.signal}</strong></div>
                  <div className="signal-row"><span>Entry</span><strong>{formatPrice(strategyResult.signal.entry_price, 2)}</strong></div>
                  <div className="signal-row"><span>Stop loss</span><strong>{formatPrice(strategyResult.signal.stop_loss, 2)}</strong></div>
                  <div className="signal-row"><span>Target</span><strong>{formatPrice(strategyResult.signal.target_price, 2)}</strong></div>
                  <p>{strategyResult.signal.explanation}</p>
                </div>
              ) : <p>No signal available yet.</p>}
            </div>
          </div>
        )
      case 'strategy':
        return (
          <div className="page-stack">
            <div className="panel-block">
              <div className="section-heading"><h3>Strategy Builder</h3></div>
              <div className="config-grid">
                <label>Market<select value={marketFilter} onChange={(event) => setMarketFilter(event.target.value as 'All' | 'India' | 'United States' | 'Indices' | 'Forex')}>
                  {['All', 'India', 'United States', 'Indices', 'Forex'].map((value) => <option key={value} value={value}>{value}</option>)}
                </select></label>
                <label>Strategy<select value={strategy} onChange={(event) => setStrategy(event.target.value)}>
                  <option value="moving_average_crossover">Moving Average Crossover</option>
                  <option value="rsi">RSI Reversal</option>
                  <option value="macd">MACD Momentum</option>
                  <option value="bollinger">Bollinger Breakout</option>
                  <option value="supertrend">Supertrend</option>
                </select></label>
                <label>Timeframe<select value={chartInterval} onChange={(event) => setChartInterval(event.target.value)}>{TIMEFRAMES.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
                <label>Short period<input type="number" value={shortWindow} onChange={(event) => setShortWindow(Number(event.target.value) || 10)} /></label>
                <label>Long period<input type="number" value={longWindow} onChange={(event) => setLongWindow(Number(event.target.value) || 30)} /></label>
                <label>RSI period<input type="number" value={rsiPeriod} onChange={(event) => setRsiPeriod(Number(event.target.value) || 14)} /></label>
              </div>
            </div>
            <div className="panel-block">
              <div className="section-heading"><h3>Rule logic</h3></div>
              <p>Entry: long when short moving average is above long moving average. Exit: close positions when the reverse cross occurs or the configured stop-loss/target is hit.</p>
              <p>All signals are calculated from historical candle data and never randomly generated.</p>
            </div>
          </div>
        )
      case 'backtesting':
        return (
          <div className="page-stack">
            <div className="panel-block">
              <div className="section-heading"><h3>Backtest engine</h3></div>
              <div className="config-grid">
                <label>Symbol<select value={selectedSymbol} onChange={(event) => setSelectedSymbol(event.target.value)}>{(marketCatalog?.markets.flatMap((section) => section.items) ?? []).map((item) => <option key={item.symbol} value={item.symbol}>{item.symbol}</option>)}</select></label>
                <label>Strategy<select value={strategy} onChange={(event) => setStrategy(event.target.value)}><option value="moving_average_crossover">Moving Average</option><option value="rsi">RSI</option><option value="macd">MACD</option><option value="bollinger">Bollinger</option><option value="supertrend">Supertrend</option></select></label>
                <label>Period<select value={chartPeriod} onChange={(event) => setChartPeriod(event.target.value)}><option value="5d">5D</option><option value="1mo">1M</option><option value="3mo">3M</option><option value="6mo">6M</option><option value="1y">1Y</option></select></label>
                <label>Initial capital<input type="number" defaultValue={100000} /></label>
                <label>Position size<input type="number" defaultValue={5000} /></label>
              </div>
            </div>
            <div className="panel-block">
              <div className="section-heading"><h3>Results</h3></div>
              {strategyError ? <p className="error-text">{strategyError}</p> : strategyResult ? (
                <div className="stat-grid">
                  <div><span>Total return</span><strong>{strategyResult.summary.total_return.toFixed(2)}%</strong></div>
                  <div><span>Win rate</span><strong>{strategyResult.summary.win_rate.toFixed(2)}%</strong></div>
                  <div><span>Profit factor</span><strong>{strategyResult.summary.profit_factor.toFixed(2)}</strong></div>
                  <div><span>Max drawdown</span><strong>{strategyResult.summary.max_drawdown.toFixed(2)}%</strong></div>
                  <div><span>Trades</span><strong>{strategyResult.summary.entries}</strong></div>
                  <div><span>Signal</span><strong>{strategyResult.signal.signal}</strong></div>
                </div>
              ) : <p>No backtest results yet.</p>}
            </div>
          </div>
        )
      case 'paper':
        return (
          <>
            <div className="paper-summary">
              <div className="glass-card"><div className="card-label">Available cash</div><div className="card-value">{formatPrice(paperCash, 2)}</div><div className="meta-row"><span>Virtual</span><strong>USD</strong></div></div>
              <div className="glass-card"><div className="card-label">Open exposure</div><div className="card-value">{formatPrice(totalOpenExposure, 2)}</div><div className="meta-row"><span>Unrealized</span><strong className={unrealizedPnl >= 0 ? 'positive' : 'negative'}>{formatPrice(unrealizedPnl, 2)}</strong></div></div>
              <div className="glass-card"><div className="card-label">Latest price</div><div className="card-value">{formatPrice(paperQuote?.price, paperQuote && paperQuote.price && paperQuote.price < 100 ? 4 : 2)}</div><div className="meta-row"><span>Symbol</span><strong>{paperSymbol}</strong></div></div>
            </div>
            <div className="panel-block">
              <div className="section-heading"><h3>Paper trading</h3></div>
              <div className="trade-actions">
                <select value={paperSymbol} onChange={(event) => setPaperSymbol(event.target.value)}>
                  {(marketCatalog?.markets.flatMap((section) => section.items) ?? []).map((item) => <option key={item.symbol} value={item.symbol}>{item.symbol}</option>)}
                </select>
                <input value={paperQty} onChange={(event) => setPaperQty(event.target.value)} type="number" min="1" />
                <button type="button" className="primary-btn" onClick={() => void handleTrade('buy')}>Buy</button>
                <button type="button" className="secondary-btn" onClick={() => void handleTrade('sell')}>Sell</button>
              </div>
              {paperError ? <p className="error-text">{paperError}</p> : null}
              <div className="orders-list">
                {paperOrders.map((order, index) => (
                  <div key={`${order.timestamp}-${index}`} className="row-card">
                    <div><strong>{order.side.toUpperCase()}</strong><small>{order.symbol}</small></div>
                    <div className="align-right"><strong>{order.quantity} @ {formatPrice(order.price, 2)}</strong><small>{formatStamp(order.timestamp)}</small></div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )
      case 'portfolio':
        return (
          <div className="page-stack">
            <div className="overview-grid">
              <div className="glass-card"><div className="card-label">Portfolio value</div><div className="card-value">{formatPrice(paperCash + totalOpenExposure, 2)}</div><div className="meta-row"><span>Cash + positions</span><strong>USD</strong></div></div>
              <div className="glass-card"><div className="card-label">Cash</div><div className="card-value">{formatPrice(paperCash, 2)}</div><div className="meta-row"><span>Available</span><strong>Virtual</strong></div></div>
              <div className="glass-card"><div className="card-label">Exposure</div><div className="card-value">{formatPrice(totalOpenExposure, 2)}</div><div className="meta-row"><span>Open</span><strong>{paperPositions.length}</strong></div></div>
              <div className="glass-card"><div className="card-label">P&L</div><div className="card-value">{formatPrice(unrealizedPnl, 2)}</div><div className="meta-row"><span>Unrealized</span><strong className={unrealizedPnl >= 0 ? 'positive' : 'negative'}>{unrealizedPnl >= 0 ? 'Positive' : 'Negative'}</strong></div></div>
            </div>
            <div className="panel-block">
              <div className="section-heading"><h3>Open positions</h3></div>
              <div className="list-stack">
                {paperPositions.length ? paperPositions.map((position) => (
                  <div key={position.symbol} className="row-card">
                    <div><strong>{position.symbol}</strong><small>{position.quantity} shares</small></div>
                    <div className="align-right"><strong>{formatPrice(position.lastPrice, 2)}</strong><small>avg {formatPrice(position.avgPrice, 2)}</small></div>
                  </div>
                )) : <p>No active positions.</p>}
              </div>
            </div>
          </div>
        )
      case 'risk':
        return (
          <div className="page-stack">
            <div className="overview-grid">
              <div className="glass-card"><div className="card-label">Provider risk</div><div className="card-value">{marketStatus.status}</div><div className="meta-row"><span>Connection</span><strong>{providerSummary.status}</strong></div></div>
              <div className="glass-card"><div className="card-label">Exposure</div><div className="card-value">{formatPrice(totalOpenExposure, 2)}</div><div className="meta-row"><span>Open positions</span><strong>{paperPositions.length}</strong></div></div>
              <div className="glass-card"><div className="card-label">Stale feed guard</div><div className="card-value">{marketHealthy ? 'Active' : 'Blocked'}</div><div className="meta-row"><span>Trading gate</span><strong>{marketHealthy ? 'Allowed' : 'Disabled'}</strong></div></div>
              <div className="glass-card"><div className="card-label">Risk note</div><div className="card-value">{providerSummary.notes}</div><div className="meta-row"><span>Action</span><strong>Require auth</strong></div></div>
            </div>
          </div>
        )
      case 'news':
        return (
          <div className="page-stack">
            <div className="panel-block">
              <div className="section-heading"><h3>Market brief</h3></div>
              <div className="list-stack">
                {(forexDashboard?.economic_calendar ?? []).map((event: any, index: number) => (
                  <div key={`${event.event}-${index}`} className="row-card">
                    <div><strong>{event.event}</strong><small>{event.currency}</small></div>
                    <div className="align-right"><strong>{event.impact}</strong><small>{event.time}</small></div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )
      case 'settings':
        return (
          <div className="page-stack">
            <div className="panel-block">
              <div className="section-heading"><h3>Environment and provider configuration</h3></div>
              <ul className="config-list">
                <li>UPSTOX_API_KEY / UPSTOX_CLIENT_CODE / UPSTOX_ACCESS_TOKEN</li>
                <li>ALPACA_API_KEY / ALPACA_API_SECRET / ALPACA_BASE_URL</li>
                <li>OANDA_API_KEY / OANDA_ACCOUNT_ID</li>
              </ul>
              <p>Credentials must be configured in the backend environment before a live provider is labeled as LIVE. Historical fallback remains allowed without credentials.</p>
            </div>
          </div>
        )
      default:
        return null
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">QX</div>
          <div>
            <div className="brand-name">QUANT-X</div>
            <div className="brand-subtitle">INTELLIGENCE TERMINAL</div>
          </div>
        </div>

        <div className="sidebar-section-label">Workspace</div>
        <nav className="nav-list" aria-label="Main navigation">
          {TABS.map((tab) => (
            <button key={tab.key} className={`nav-item ${activeTab === tab.key ? 'active' : ''}`} onClick={() => setActiveTab(tab.key)} type="button">
              <span className="nav-icon">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="status-chip"><span className="live-dot" />SYSTEM ONLINE</div>
          <div className="profile-row">
            <div className="profile-badge">Q</div>
            <div>
              <strong>QUANT-X User</strong>
              <small>Research account</small>
            </div>
          </div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <div className="breadcrumb">Workspace / {activeTab.toUpperCase()}</div>
            <h1>{
              activeTab === 'overview' ? 'Overview' :
              activeTab === 'markets' ? 'Market Dashboard' :
              activeTab === 'charts' ? 'Interactive Charts' :
              activeTab === 'ai' ? 'AI Signals' :
              activeTab === 'algo' ? 'Algorithmic Trading' :
              activeTab === 'strategy' ? 'Strategy Builder' :
              activeTab === 'backtesting' ? 'Backtesting' :
              activeTab === 'paper' ? 'Paper Trading' :
              activeTab === 'portfolio' ? 'Portfolio' :
              activeTab === 'risk' ? 'Risk Management' :
              activeTab === 'news' ? 'News' :
              'Settings'
            }</h1>
          </div>
          <div className="topbar-actions">
            <div className={`connection-pill ${marketHealthy ? 'active' : 'offline'}`}><span className="live-dot" />{providerSummary.status || 'DISCONNECTED'}</div>
            <button className="icon-button" type="button">⟳</button>
            <div className="mini-avatar">Q</div>
          </div>
        </header>

        <div className="dashboard-wrap">
          <div className="notice-panel"><span>Feed status</span>{marketStatus.warning || 'Historical data is available without paid credentials.'}</div>
          {renderPage()}
        </div>
      </main>
    </div>
  )
}

export default App
