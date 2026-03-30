import React, { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  TrendingUp,
  History,
  Settings,
  Zap,
  Activity,
  DollarSign,
  Target,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Play,
  Square,
  RefreshCw,
  Trash2,
  TrendingDown,
  Minus,
  Brain
} from 'lucide-react'

import Dashboard from './pages/Dashboard'
import Trades from './pages/Trades'
import TradeDetail from './pages/TradeDetail'
import Strategies from './pages/Strategies'
import Performance from './pages/Performance'
import Positions from './pages/Positions'
import Logs from './pages/Logs'
import AIActivity from './pages/AIActivity'
import SystemStatus from './components/SystemStatus'

const NavLink = ({ to, icon: Icon, children }) => {
  const location = useLocation()
  const isActive = location.pathname === to ||
    (to !== '/' && location.pathname.startsWith(to))

  return (
    <Link
      to={to}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-xs ${
        isActive
          ? 'bg-blue-600 text-white'
          : 'text-gray-400 hover:bg-gray-800 hover:text-white'
      }`}
    >
      <Icon size={14} />
      <span>{children}</span>
    </Link>
  )
}

function App() {
  const [status, setStatus] = useState(null)
  const [prices, setPrices] = useState({})
  const [ws, setWs] = useState(null)
  const [biases, setBiases] = useState({})
  const [biasTimeframe, setBiasTimeframe] = useState('H1')
  const [symbolUnits, setSymbolUnits] = useState({})  // Store as strings to preserve trailing zeros
  const [candleCount, setCandleCount] = useState(0)
  const [marketOpen, setMarketOpen] = useState(true)  // Assume open unless we detect closed

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/status')
      const data = await res.json()
      setStatus(data)
      setMarketOpen(data.market_open !== false)
    } catch (err) {
      console.error('Failed to fetch status:', err)
    }
  }

  const fetchPrices = async () => {
    try {
      const res = await fetch('/api/prices')
      const data = await res.json()
      setPrices(prev => ({ ...prev, ...data }))
    } catch (err) {
      console.error('Failed to fetch prices:', err)
    }
  }

  const fetchBiases = async () => {
    try {
      const res = await fetch(`/api/symbol-bias?timeframe=${biasTimeframe}`)
      const data = await res.json()
      setBiases(data.biases || {})
    } catch (err) {
      console.error('Failed to fetch biases:', err)
    }
  }

  const fetchSymbolUnits = async () => {
    try {
      const res = await fetch('/api/symbol-units')
      const data = await res.json()
      setSymbolUnits(data || {})
    } catch (err) {
      console.error('Failed to fetch symbol units:', err)
    }
  }

  const fetchCandleCount = async () => {
    try {
      const res = await fetch('/api/candles/count')
      const data = await res.json()
      setCandleCount(data.count || 0)
    } catch (err) {
      // Silently fail - candle count is not critical
    }
  }

  const saveSymbolUnit = async (symbol, units) => {
    try {
      await fetch('/api/symbol-units', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, units: units ? parseFloat(units) : null })
      })
      fetchSymbolUnits()
    } catch (err) {
      console.error('Failed to save symbol units:', err)
    }
  }

  useEffect(() => {
    fetchStatus()
    fetchPrices()
    fetchBiases()
    fetchSymbolUnits()
    fetchCandleCount()
    const interval = setInterval(fetchStatus, 5000)
    const biasInterval = setInterval(fetchBiases, 30000)
    const candleInterval = setInterval(fetchCandleCount, 60000)
    return () => {
      clearInterval(interval)
      clearInterval(biasInterval)
      clearInterval(candleInterval)
    }
  }, [biasTimeframe])

  useEffect(() => {
    const websocket = new WebSocket(`ws://${window.location.host}/ws`)
    
    websocket.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'tick') {
        setPrices(prev => ({
          ...prev,
          [data.symbol]: {
            price: data.price,
            bid: data.bid,
            ask: data.ask,
            source: data.source
          }
        }))
      }
    }

    websocket.onerror = (err) => {
      console.error('WebSocket error:', err)
    }

    setWs(websocket)

    return () => {
      websocket.close()
    }
  }, [])

  const toggleEngine = async () => {
    const endpoint = status?.running ? '/api/engine/stop' : '/api/engine/start'
    await fetch(endpoint, { method: 'POST' })
    fetchStatus()
  }

  const toggleAutoTrade = async () => {
    await fetch('/api/auto-trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !status?.auto_trade })
    })
    fetchStatus()
  }

  const toggleApproval = async () => {
    await fetch('/api/require-approval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ required: !status?.require_approval })
    })
    fetchStatus()
  }

  const [showClearMenu, setShowClearMenu] = useState(false)

  const clearHistory = async (type) => {
    if (!confirm(`Are you sure you want to clear ${type}? This cannot be undone.`)) {
      return
    }
    
    const endpoint = type === 'all' ? '/api/history' : `/api/${type}`
    await fetch(endpoint, { method: 'DELETE' })
    setShowClearMenu(false)
    fetchStatus()
  }

  return (
    <BrowserRouter>
      <div className="flex h-screen">
        {/* Sidebar */}
        <aside className="w-72 bg-gray-800 border-r border-gray-700 flex flex-col">
          <div className="p-3 border-b border-gray-700">
            <div className="flex items-center justify-between">
              <h1 className="text-lg font-bold flex items-center gap-2">
                <Zap className="text-yellow-500" size={16} />
                Trading Station
              </h1>
              {candleCount > 0 && (
                <span className="text-xs text-gray-400" title="AI training candles">
                  {candleCount.toLocaleString()}
                </span>
              )}
            </div>
          </div>

          {/* Active Feed Symbols with Bias */}
          <div className="p-3 border-b border-gray-700">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <div className="text-xs text-gray-500 uppercase">
                  Symbols ({Object.keys(prices).length})
                </div>
                {(() => {
                  return (
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      marketOpen ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400'
                    }`}>
                      {marketOpen ? 'Markets Open' : 'Markets Closed'}
                    </span>
                  )
                })()}
              </div>
              <select
                value={biasTimeframe}
                onChange={(e) => setBiasTimeframe(e.target.value)}
                className="bg-gray-700 text-xs rounded px-2 py-1 text-gray-300"
              >
                <option value="M5">M5</option>
                <option value="M15">M15</option>
                <option value="H1">H1</option>
                <option value="H4">H4</option>
                <option value="D1">D1</option>
              </select>
            </div>
            {Object.keys(prices).length > 0 ? (
              <div className="space-y-1">
                {Object.entries(prices).map(([symbol, data]) => {
                  const price = typeof data === 'object' ? data.price : data
                  const source = typeof data === 'object' ? data.source : ''
                  const isForex = symbol.includes('USD') && !symbol.includes('USDT')
                  const isGold = symbol.includes('XAU')
                  const isSilver = symbol.includes('XAG')
                  const decimals = (isGold || isSilver) ? 3 : isForex ? 5 : 2
                  const bias = biases[symbol]
                  const biasColor = bias?.bias === 'bullish' ? 'text-green-400' :
                                   bias?.bias === 'bearish' ? 'text-red-400' : 'text-gray-400'
                  const BiasIcon = bias?.bias === 'bullish' ? TrendingUp :
                                   bias?.bias === 'bearish' ? TrendingDown : Minus
                  const unitVal = symbolUnits[symbol]

                  return (
                    <div key={symbol} className="flex items-center justify-between text-xs py-0.5">
                      <div className="flex items-center gap-1 w-24">
                        <BiasIcon size={10} className={biasColor} />
                        <span className="text-gray-400 truncate" title={source}>{symbol}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <input
                          type="text"
                          inputMode="decimal"
                          placeholder="U"
                          value={unitVal !== undefined && unitVal !== null && unitVal !== '' ? (parseFloat(unitVal) || 0).toFixed(2) : ''}
                          onChange={(e) => {
                            const val = e.target.value
                            // Allow empty or valid decimal numbers
                            if (val === '' || /^\d*\.?\d*$/.test(val)) {
                              setSymbolUnits(prev => ({ ...prev, [symbol]: val || null }))
                            }
                          }}
                          onBlur={(e) => saveSymbolUnit(symbol, e.target.value)}
                          className="w-14 bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-xs text-white text-right [-moz-appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                          title={unitVal ? `Will trade ${unitVal} units` : 'No trade (blank = disabled)'}
                        />
                        <span className="font-mono text-gray-300 w-20 text-right">
                          {price?.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
                        </span>
                        <span className={`w-10 text-right font-medium ${biasColor}`}>
                          {bias ? bias.strength : ''}%
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="text-gray-500 text-sm">No feed connected</div>
            )}
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-4 space-y-2">
            <NavLink to="/" icon={LayoutDashboard}>Dashboard</NavLink>
            <NavLink to="/positions" icon={Activity}>Open Positions</NavLink>
            <NavLink to="/trades" icon={History}>Trade History</NavLink>
            <NavLink to="/strategies" icon={Target}>Strategies</NavLink>
            <NavLink to="/ai-activity" icon={Brain}>AI Activity</NavLink>
            <NavLink to="/performance" icon={TrendingUp}>Performance</NavLink>
            <NavLink to="/logs" icon={Activity}>Logs</NavLink>
          </nav>

          {/* Engine Controls */}
          <div className="p-3 border-t border-gray-700 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">Engine</span>
              <button
                onClick={toggleEngine}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${
                  status?.running
                    ? 'bg-red-600 hover:bg-red-700'
                    : 'bg-green-600 hover:bg-green-700'
                }`}
              >
                {status?.running ? <Square size={10} /> : <Play size={10} />}
                {status?.running ? 'Stop' : 'Start'}
              </button>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">Auto Trade</span>
              <button
                onClick={toggleAutoTrade}
                className={`px-2 py-1 rounded text-xs font-medium ${
                  status?.auto_trade
                    ? 'bg-green-600'
                    : 'bg-gray-600'
                }`}
              >
                {status?.auto_trade ? 'ON' : 'OFF'}
              </button>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">AI Approval</span>
              <button
                onClick={toggleApproval}
                className={`px-2 py-1 rounded text-xs font-medium ${
                  status?.require_approval
                    ? 'bg-blue-600'
                    : 'bg-gray-600'
                }`}
              >
                {status?.require_approval ? 'ON' : 'OFF'}
              </button>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">Validator</span>
              <span className="px-2 py-1 rounded text-xs font-medium bg-purple-600">
                AI
              </span>
            </div>

            {/* Clear History */}
            <div className="pt-2 border-t border-gray-600 mt-2">
              <button
                onClick={() => setShowClearMenu(!showClearMenu)}
                className="flex items-center gap-1 w-full px-2 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-300"
              >
                <Trash2 size={10} />
                Clear
              </button>

              {showClearMenu && (
                <div className="absolute bottom-full left-0 right-0 mb-1 bg-gray-700 rounded shadow-lg border border-gray-600 overflow-hidden">
                  <button
                    onClick={() => clearHistory('trades')}
                    className="w-full px-2 py-1 text-left text-xs hover:bg-gray-600 text-gray-300"
                  >
                    Clear Trades
                  </button>
                  <button
                    onClick={() => clearHistory('signals')}
                    className="w-full px-2 py-1 text-left text-xs hover:bg-gray-600 text-gray-300"
                  >
                    Clear Signals
                  </button>
                  <button
                    onClick={() => clearHistory('all')}
                    className="w-full px-2 py-1 text-left text-xs hover:bg-red-600 text-white"
                  >
                    Clear All
                  </button>
                </div>
              )}
            </div>
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<Dashboard status={status} />} />
            <Route path="/positions" element={<Positions />} />
            <Route path="/trades" element={<Trades />} />
            <Route path="/trades/:id" element={<TradeDetail />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/ai-activity" element={<AIActivity />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/logs" element={<Logs />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
