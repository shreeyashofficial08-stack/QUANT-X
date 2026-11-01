
import { useState } from 'react'
import './App.css'

const stocks = [
  { symbol: 'RELIANCE', name: 'Reliance Industries', price: '1,456.80', change: '+2.45%', positive: true },
  { symbol: 'TCS', name: 'Tata Consultancy', price: '3,842.50', change: '+1.32%', positive: true },
  { symbol: 'HDFCBANK', name: 'HDFC Bank', price: '1,682.20', change: '-0.84%', positive: false },
  { symbol: 'INFY', name: 'Infosys Limited', price: '1,512.60', change: '+1.76%', positive: true },
  { symbol: 'ICICIBANK', name: 'ICICI Bank', price: '1,245.30', change: '-0.32%', positive: false },
]

const usStocks = [
  { symbol: 'AAPL', name: 'Apple Inc.', price: '269.40', change: '+1.82%', positive: true },
  { symbol: 'NVDA', name: 'NVIDIA Corp.', price: '198.60', change: '+3.24%', positive: true },
  { symbol: 'MSFT', name: 'Microsoft', price: '521.30', change: '-0.62%', positive: false },
  { symbol: 'TSLA', name: 'Tesla Inc.', price: '442.10', change: '+2.15%', positive: true },
  { symbol: 'AMZN', name: 'Amazon', price: '228.75', change: '+0.91%', positive: true },
]

const chartValues = [36, 33, 39, 31, 35, 27, 32, 25, 30, 21, 25, 18, 24, 15, 19, 12, 17, 9, 13, 5, 10, 3, 8, 1]

function App() {
  const [market, setMarket] = useState('INDIA')
  const [activeNav, setActiveNav] = useState('Overview')
  const [period, setPeriod] = useState('1D')
  const [search, setSearch] = useState('')

  const currentStocks = market === 'INDIA' ? stocks : usStocks
  const filteredStocks = currentStocks.filter(stock =>
    stock.symbol.toLowerCase().includes(search.toLowerCase()) ||
    stock.name.toLowerCase().includes(search.toLowerCase())
  )

  const chartPoints = chartValues.map((value, index) =>
    `${index * 40},${value * 5 + 20}`
  ).join(' ')

  const navItems = [
    { name: 'Overview', icon: '◫' },
    { name: 'Markets', icon: '▥' },
    { name: 'AI Signals', icon: '✳' },
    { name: 'Strategies', icon: '⌘' },
    { name: 'Backtesting', icon: '◷' },
    { name: 'Paper Trading', icon: '⇄' },
    { name: 'Portfolio', icon: '◉' },
  ]

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">Q</div>
          <div>
            <h2>QUANT<span>-X</span></h2>
            <small>INTELLIGENCE TERMINAL</small>
          </div>
        </div>

        <div className="sidebar-label">WORKSPACE</div>
        <nav>
          {navItems.map(item => (
            <button
              key={item.name}
              className={`nav-item ${activeNav === item.name ? 'active' : ''}`}
              onClick={() => setActiveNav(item.name)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.name}
              {item.name === 'AI Signals' && <span className="nav-new">AI</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-label tools-label">SYSTEM</div>
        <button className="nav-item"><span className="nav-icon">⚙</span> Settings</button>
        <button className="nav-item"><span className="nav-icon">◈</span> Documentation</button>

        <div className="sidebar-bottom">
          <div className="status-indicator"><span /> SYSTEM ONLINE</div>
          <div className="profile">
            <div className="avatar">QX</div>
            <div><strong>QUANT-X User</strong><small>Research Account</small></div>
            <span className="profile-menu">•••</span>
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <div className="breadcrumb">WORKSPACE <span>/</span> {activeNav.toUpperCase()}</div>
            <h1>{activeNav === 'Overview' ? 'Market Overview' : activeNav}</h1>
          </div>
          <div className="topbar-right">
            <div className="connection"><span /> DEMO MODE</div>
            <button className="icon-button" title="Notifications">♧</button>
            <div className="top-avatar">Q</div>
          </div>
        </header>

        <div className="dashboard">
          <div className="welcome-row">
            <div>
              <h2>Market Intelligence <span className="sparkle">✳</span></h2>
              <p>Track markets. Discover opportunities. Make data-driven decisions.</p>
            </div>
            <div className="market-switch">
              <button className={market === 'INDIA' ? 'selected' : ''} onClick={() => setMarket('INDIA')}>🇮🇳 INDIA</button>
              <button className={market === 'US' ? 'selected' : ''} onClick={() => setMarket('US')}>🇺🇸 UNITED STATES</button>
            </div>
          </div>

          <div className="demo-notice">
            <span>ⓘ</span> DEMONSTRATION DATA — Market prices and metrics below are illustrative, not live exchange data.
          </div>

          <section className="metric-grid">
            <div className="metric-card">
              <div className="metric-heading">MARKET INDEX <span>↗</span></div>
              <div className="metric-value">{market === 'INDIA' ? '26,102.45' : '23,458.20'}</div>
              <div className="metric-change positive">↑ 1.24% <span>Today</span></div>
              <div className="metric-footer"> {market === 'INDIA' ? 'NIFTY 50' : 'NASDAQ 100'} </div>
            </div>
            <div className="metric-card">
              <div className="metric-heading">MARKET SENTIMENT <span>◉</span></div>
              <div className="metric-value">Bullish</div>
              <div className="sentiment-bar"><span /></div>
              <div className="metric-footer">BUYING PRESSURE <strong>72%</strong></div>
            </div>
            <div className="metric-card">
              <div className="metric-heading">VOLUME TRADED <span>▥</span></div>
              <div className="metric-value">{market === 'INDIA' ? '₹ 8.42B' : '$ 42.8B'}</div>
              <div className="metric-change positive">↑ 8.6% <span>vs previous session</span></div>
              <div className="metric-footer">TOTAL MARKET VOLUME</div>
            </div>
            <div className="metric-card">
              <div className="metric-heading">AI CONFIDENCE <span>✳</span></div>
              <div className="metric-value">87.4<span className="percent">%</span></div>
              <div className="metric-change positive">High confidence</div>
              <div className="metric-footer">ILLUSTRATIVE MODEL OUTPUT</div>
            </div>
          </section>

          <section className="content-grid">
            <div className="panel chart-panel">
              <div className="panel-header">
                <div>
                  <div className="panel-eyebrow">MARKET PERFORMANCE</div>
                  <h3>{market === 'INDIA' ? 'NIFTY 50' : 'NASDAQ 100'} <span className="live-dot" /></h3>
                  <div className="chart-price">{market === 'INDIA' ? '26,102.45' : '23,458.20'} <span className="positive">+1.24%</span></div>
                </div>
                <div className="period-selector">
                  {['1D', '1W', '1M', '3M', '1Y', 'ALL'].map(p => (
                    <button key={p} className={period === p ? 'chosen' : ''} onClick={() => setPeriod(p)}>{p}</button>
                  ))}
                </div>
              </div>

              <div className="chart-container">
                <div className="chart-y-labels">
                  <span>26,500</span><span>26,000</span><span>25,500</span><span>25,000</span><span>24,500</span>
                </div>
                <svg className="market-chart" viewBox="0 0 920 250" preserveAspectRatio="none">
                  <defs>
                    <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#16c784" stopOpacity=".25" />
                      <stop offset="100%" stopColor="#16c784" stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  {[30, 80, 130, 180, 230].map(y => <line key={y} x1="0" y1={y} x2="920" y2={y} stroke="#202a35" strokeDasharray="4 6" />)}
                  <polygon points={`0,250 ${chartPoints} 920,250`} fill="url(#chartFill)" />
                  <polyline points={chartPoints} fill="none" stroke="#16c784" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                </svg>
              </div>
              <div className="chart-x-labels"><span>09:15</span><span>10:30</span><span>11:45</span><span>13:00</span><span>14:15</span><span>15:30</span></div>
              <div className="chart-footer"><span><i className="legend-dot" /> INDEX PRICE</span><span>Illustrative chart · Not connected to an exchange</span></div>
            </div>

            <div className="panel ai-panel">
              <div className="panel-header">
                <div><div className="panel-eyebrow">MACHINE LEARNING</div><h3><span className="sparkle">✳</span> AI Insights</h3></div>
                <span className="ai-badge">AI ENGINE</span>
              </div>
              <div className="ai-score">
                <div className="score-ring"><div><strong>87</strong><small>/100</small></div></div>
                <div><strong>Positive Outlook</strong><p>Illustrative market assessment</p></div>
              </div>
              <div className="insight-item"><span className="insight-icon green">↗</span><div><strong>Momentum</strong><p>Positive trend strength</p></div><b className="positive">Strong</b></div>
              <div className="insight-item"><span className="insight-icon blue">⌁</span><div><strong>Volatility</strong><p>Illustrative risk estimate</p></div><b>Moderate</b></div>
              <div className="insight-item"><span className="insight-icon purple">✳</span><div><strong>AI Signal</strong><p>Example model output</p></div><b className="positive">BUY</b></div>
              <button className="full-button" onClick={() => setActiveNav('AI Signals')}>Explore AI Signals <span>→</span></button>
            </div>
          </section>

          <section className="panel watchlist-panel">
            <div className="panel-header watchlist-header">
              <div><div className="panel-eyebrow">YOUR MARKET TRACKER</div><h3>Market Watchlist</h3></div>
              <input className="search-input" placeholder="⌕  Search assets..." value={search} onChange={e => setSearch(e.target.value)} />
            </div>
            <div className="stock-table">
              <div className="stock-row stock-head"><span>ASSET</span><span>PRICE ({market === 'INDIA' ? 'INR' : 'USD'})</span><span>24H CHANGE</span><span>MARKET</span></div>
              {filteredStocks.map(stock => (
                <div className="stock-row" key={stock.symbol}>
                  <div className="stock-name"><div className="stock-symbol">{stock.symbol.slice(0, 2)}</div><div><strong>{stock.symbol}</strong><small>{stock.name}</small></div></div>
                  <strong>{market === 'INDIA' ? '₹' : '$'} {stock.price}</strong>
                  <span className={stock.positive ? 'positive' : 'negative'}>{stock.change}</span>
                  <span className="market-tag">{market}</span>
                </div>
              ))}
              {filteredStocks.length === 0 && <div className="empty-state">No matching assets found.</div>}
            </div>
          </section>

          <footer className="dashboard-footer">
            <span>QUANT-X TERMINAL <span className="footer-separator">•</span> VERSION 1.0</span>
            <span>EDUCATIONAL RESEARCH PLATFORM <span className="footer-separator">•</span> NOT FINANCIAL ADVICE</span>
          </footer>
        </div>
      </main>
    </div>
  )
}

export default App
