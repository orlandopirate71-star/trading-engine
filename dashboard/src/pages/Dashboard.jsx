import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Activity,
  Target,
  AlertCircle,
  CheckCircle,
  Clock,
  Globe,
  Moon
} from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import SystemStatus from '../components/SystemStatus'

const getTradingSession = () => {
  const utcHour = new Date().getUTCHours()
  const dayOfWeek = new Date().getUTCDay()
  // Forex sessions in UTC
  if (utcHour >= 22 || utcHour < 6) return { name: 'Asian', color: 'bg-purple-500', textColor: 'text-purple-400' }
  if (utcHour >= 6 && utcHour < 9) return { name: 'Tokyo', color: 'bg-pink-500', textColor: 'text-pink-400' }
  if (utcHour >= 9 && utcHour < 12) return { name: 'London', color: 'bg-blue-500', textColor: 'text-blue-400' }
  if (utcHour >= 12 && utcHour < 22) return { name: 'New York', color: 'bg-green-500', textColor: 'text-green-400' }
  return { name: 'Closed', color: 'bg-gray-500', textColor: 'text-gray-400' }
}

const isMarketOpen = () => {
  const now = new Date()
  const utcHour = now.getUTCHours()
  const dayOfWeek = now.getUTCDay() // 0 = Sunday, 6 = Saturday

  // Forex is closed on weekends (Sat/Sun full day, and some brokers Sun evening)
  if (dayOfWeek === 0) return { open: false, label: 'Market Closed', subtext: 'Opens Sunday 22:00 UTC' }
  if (dayOfWeek === 6) return { open: false, label: 'Market Closed', subtext: 'Opens Sunday 22:00 UTC' }

  // Weekdays: market open 24h (but real activity 22:00-22:00 UTC)
  // Show as "open" during active trading hours
  if (utcHour >= 22 || utcHour < 6) {
    return { open: true, label: 'Market Open', subtext: 'Sydney/Asian Session' }
  }
  return { open: true, label: 'Market Open', subtext: 'London/New York Session' }
}

const StatCard = ({ title, value, icon: Icon, color, subtext }) => (
  <div className="bg-gray-800 rounded-xl p-3 border border-gray-700">
    <div className="flex items-center justify-between mb-1">
      <span className="text-gray-400 text-xs">{title}</span>
      <Icon className={color} size={14} />
    </div>
    <div className="text-lg font-bold">{value}</div>
    {subtext && <div className="text-xs text-gray-500">{subtext}</div>}
  </div>
)

const RecentTrade = ({ trade }) => {
  const isWin = trade.pnl > 0
  const isPending = trade.status === 'pending' || trade.status === 'approved'

  return (
    <Link
      to={`/trades/${trade.id}`}
      className="flex items-center justify-between p-2 bg-gray-800 rounded hover:bg-gray-750 transition-colors"
    >
      <div className="flex items-center gap-2">
        <div className={`w-6 h-6 rounded-full flex items-center justify-center ${
          trade.direction === 'long' ? 'bg-green-900' : 'bg-red-900'
        }`}>
          {trade.direction === 'long' ?
            <TrendingUp className="text-green-400" size={12} /> :
            <TrendingDown className="text-red-400" size={12} />
          }
        </div>
        <div>
          <div className="font-medium text-xs">{trade.symbol}</div>
          <div className="text-xs text-gray-400">{trade.strategy_name}</div>
        </div>
      </div>
      <div className="text-right">
        {trade.status === 'closed' ? (
          <>
            <div className={`font-mono font-bold text-xs ${isWin ? 'text-green-400' : 'text-red-400'}`}>
              {isWin ? '+' : ''}{trade.pnl?.toFixed(4)}
            </div>
            <div className="text-xs text-gray-400">
              {trade.pnl_percent?.toFixed(2)}%
            </div>
          </>
        ) : (
          <div className={`flex items-center gap-1 text-xs ${
            trade.status === 'approved' ? 'text-yellow-400' :
            trade.status === 'open' ? 'text-blue-400' : 'text-gray-400'
          }`}>
            {trade.status === 'approved' && <Clock size={12} />}
            {trade.status === 'open' && <Activity size={12} />}
            <span className="capitalize">{trade.status}</span>
          </div>
        )}
      </div>
    </Link>
  )
}

const OpenPosition = ({ position }) => {
  const isProfit = position.unrealized_pnl >= 0

  return (
    <div className="p-2 bg-gray-800 rounded-lg border border-gray-700">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <div className={`px-2 py-0.5 rounded text-xs font-bold ${
            position.direction === 'long' ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400'
          }`}>
            {position.direction?.toUpperCase()}
          </div>
          <span className="font-medium text-xs">{position.symbol}</span>
          <span className={`px-2 py-0.5 rounded text-xs ${
            position.broker === 'oanda' ? 'bg-blue-900 text-blue-400' : 'bg-gray-700 text-gray-400'
          }`}>
            {position.broker === 'oanda' ? 'OANDA' : 'Paper'}
          </span>
        </div>
        <div className={`font-mono font-bold text-xs ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
          {isProfit ? '+' : ''}{position.unrealized_pnl?.toFixed(4)}
        </div>
      </div>
      <div className="text-xs text-gray-500 mb-1">{position.strategy_name}</div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-gray-400">Entry</div>
          <div className="font-mono">{position.entry_price?.toLocaleString()}</div>
        </div>
        <div>
          <div className="text-gray-400">Current</div>
          <div className="font-mono">{position.current_price?.toLocaleString()}</div>
        </div>
        <div>
          <div className="text-gray-400">Qty</div>
          <div className="font-mono">{position.quantity}</div>
        </div>
      </div>
      {(position.stop_loss || position.take_profit) && (
        <div className="flex gap-4 mt-2 pt-2 border-t border-gray-700 text-xs">
          {position.stop_loss && (
            <div className="text-red-400">
              SL: {position.stop_loss?.toLocaleString()}
            </div>
          )}
          {position.take_profit && (
            <div className="text-green-400">
              TP: {position.take_profit?.toLocaleString()}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function Dashboard({ status }) {
  const [trades, setTrades] = useState([])
  const [positions, setPositions] = useState([])
  const [performance, setPerformance] = useState(null)
  const [balance, setBalance] = useState(null)
  const [brokerInfo, setBrokerInfo] = useState(null)
  const [oandaAccount, setOandaAccount] = useState(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [tradesRes, positionsRes, perfRes, balanceRes, brokerRes] = await Promise.all([
          fetch('/api/trades?limit=10'),
          fetch('/api/positions'),
          fetch('/api/performance?days=7'),
          fetch('/api/balance'),
          fetch('/api/broker')
        ])
        
        setTrades((await tradesRes.json()).trades)
        const posData = await positionsRes.json()
        setPositions(posData.positions || [])
        setPerformance(await perfRes.json())
        setBalance(await balanceRes.json())
        
        const broker = await brokerRes.json()
        setBrokerInfo(broker)
        
        // If OANDA is available, fetch OANDA account data
        if (broker.oanda_available) {
          const oandaRes = await fetch('/api/oanda/account')
          setOandaAccount(await oandaRes.json())
        }
      } catch (err) {
        console.error('Failed to fetch dashboard data:', err)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 10000)
    return () => clearInterval(interval)
  }, [])

  const stats = performance?.stats || {}

  const session = getTradingSession()
  const market = isMarketOpen()

  const today = new Date()
  const dateStr = today.toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric'
  })

  return (
    <div className="p-6 space-y-6">
      <SystemStatus />

      {/* Market Status Banner */}
      {!market.open && (
        <div className="bg-gray-800/50 border border-gray-700 rounded p-3 flex items-center justify-between text-xs">
          <div className="flex items-center gap-3">
            <Moon size={16} className="text-gray-400" />
            <div>
              <div className="font-medium text-gray-300">Market Closed</div>
              <div className="text-gray-500">No trading signals will be generated until markets open</div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-gray-400">Next Open</div>
            <div className="font-mono text-gray-300">Sunday 22:00 UTC</div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold">Dashboard</h1>
          <div className="text-xs text-gray-400">{dateStr}</div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${market.open ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
            <span className="text-xs text-gray-400">{market.label}</span>
            <span className="text-xs text-gray-500">({market.subtext})</span>
          </div>
          <div className="flex items-center gap-2">
            <Globe size={14} className={session.textColor} />
            <span className="text-xs text-gray-400">Session:</span>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${session.color} text-white`}>
              {session.name}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${status?.running ? 'bg-green-500 animate-pulse' : 'bg-gray-500'}`} />
            <span className="text-xs text-gray-400">
              {status?.running ? 'Engine Running' : 'Engine Stopped'}
            </span>
          </div>
        </div>
      </div>

      {/* OANDA Account Card - Show when OANDA is available */}
      {oandaAccount && (
        <div className="bg-gradient-to-r from-blue-900 to-blue-800 rounded-xl p-4 border border-blue-700">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-blue-700 rounded-lg flex items-center justify-center">
                <DollarSign className="text-blue-300" size={18} />
              </div>
              <div>
                <div className="text-blue-300 text-xs">OANDA Demo Account</div>
                <div className="text-xl font-bold">
                  {oandaAccount.currency === 'GBP' ? '£' : '$'}
                  {oandaAccount.balance?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </div>
              </div>
            </div>
            <div className={`px-2 py-0.5 rounded-full text-xs ${
              brokerInfo?.mode === 'oanda' ? 'bg-green-600 text-white' : 'bg-gray-600 text-gray-300'
            }`}>
              {brokerInfo?.mode === 'oanda' ? 'LIVE' : 'Paper Mode'}
            </div>
          </div>
          <div className="grid grid-cols-4 gap-2 text-xs">
            <div>
              <div className="text-blue-400">NAV</div>
              <div className="font-mono">{oandaAccount.currency === 'GBP' ? '£' : '$'}{oandaAccount.nav?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
            </div>
            <div>
              <div className="text-blue-400">Unrealized P&L</div>
              <div className={`font-mono ${oandaAccount.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {oandaAccount.unrealized_pnl >= 0 ? '+' : ''}{oandaAccount.currency === 'GBP' ? '£' : '$'}{oandaAccount.unrealized_pnl?.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-blue-400">Margin Used</div>
              <div className="font-mono">{oandaAccount.currency === 'GBP' ? '£' : '$'}{oandaAccount.margin_used?.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-blue-400">Open Trades</div>
              <div className="font-mono">{oandaAccount.open_trade_count}</div>
            </div>
          </div>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          title={brokerInfo?.mode === 'oanda' ? "OANDA Balance" : "Paper Balance"}
          value={`${brokerInfo?.mode === 'oanda' && oandaAccount ? (oandaAccount.currency === 'GBP' ? '£' : '$') : '$'}${
            brokerInfo?.mode === 'oanda' && oandaAccount
              ? oandaAccount.balance?.toLocaleString(undefined, { minimumFractionDigits: 2 })
              : balance?.total?.toLocaleString(undefined, { minimumFractionDigits: 2 }) || '0.00'
          }`}
          icon={DollarSign}
          color="text-green-400"
          subtext={brokerInfo?.mode === 'oanda' ? `${oandaAccount?.open_trade_count || 0} open trades` : (balance?.pnl >= 0 ? `+$${balance?.pnl?.toFixed(2)}` : `-$${Math.abs(balance?.pnl || 0).toFixed(2)}`)}
        />
        <StatCard
          title="Win Rate"
          value={`${stats.win_rate?.toFixed(1) || 0}%`}
          icon={Target}
          color="text-blue-400"
          subtext={`${stats.winning_trades || 0}W / ${stats.losing_trades || 0}L`}
        />
        <StatCard
          title="Total P&L (7d)"
          value={`${stats.total_pnl >= 0 ? '+' : ''}$${stats.total_pnl?.toFixed(2) || '0.00'}`}
          icon={stats.total_pnl >= 0 ? TrendingUp : TrendingDown}
          color={stats.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
          subtext={`${stats.total_trades || 0} trades`}
        />
        <StatCard
          title="Open Positions"
          value={positions.length}
          icon={Activity}
          color="text-yellow-400"
          subtext={`${status?.pending_trades || 0} pending`}
        />
      </div>

      {/* P&L Chart */}
      {performance?.cumulative_pnl?.length > 0 && (
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <h2 className="text-sm font-semibold mb-2">Cumulative P&L (7 Days)</h2>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={performance.cumulative_pnl}>
                <XAxis
                  dataKey="date"
                  stroke="#6b7280"
                  tickFormatter={(val) => new Date(val).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                />
                <YAxis stroke="#6b7280" />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }}
                  labelStyle={{ color: '#9ca3af' }}
                />
                <Line
                  type="monotone"
                  dataKey="cumulative_pnl"
                  stroke="#10b981"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Open Positions */}
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <h2 className="text-sm font-semibold mb-2 flex items-center gap-2">
            <Activity size={16} className="text-yellow-400" />
            Open Positions
          </h2>
          {positions.length > 0 ? (
            <div className="space-y-2">
              {positions.map((pos, i) => (
                <OpenPosition key={i} position={pos} />
              ))}
            </div>
          ) : (
            <div className="text-center py-4 text-gray-500 text-xs">
              No open positions
            </div>
          )}
        </div>

        {/* Recent Trades */}
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold">Recent Trades</h2>
            <Link to="/trades" className="text-xs text-blue-400 hover:text-blue-300">
              View All →
            </Link>
          </div>
          {trades.length > 0 ? (
            <div className="space-y-1">
              {trades.slice(0, 5).map((trade) => (
                <RecentTrade key={trade.id} trade={trade} />
              ))}
            </div>
          ) : (
            <div className="text-center py-4 text-gray-500 text-xs">
              No trades yet
            </div>
          )}
        </div>
      </div>

      {/* Active Strategies */}
      <div className="bg-gray-800 rounded-xl p-3 border border-gray-700">
        <h2 className="text-xs font-semibold mb-2 flex items-center gap-2">
          <Target size={12} className="text-blue-400" />
          Active Strategies
        </h2>
        {status?.strategies?.length > 0 ? (
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
            {status.strategies.map((strat) => (
              <div
                key={strat.name}
                className={`p-2 rounded border text-xs ${
                  strat.enabled
                    ? 'border-green-700 bg-green-900/20'
                    : 'border-gray-700 bg-gray-900/50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{strat.name}</span>
                  {strat.enabled ? (
                    <CheckCircle size={12} className="text-green-400" />
                  ) : (
                    <AlertCircle size={12} className="text-gray-500" />
                  )}
                </div>
                {strat.error && (
                  <div className="text-red-400 mt-1 truncate">
                    {strat.error}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-4 text-gray-500 text-xs">
            No strategies loaded. Add .py files to the strategies folder.
          </div>
        )}
      </div>
    </div>
  )
}
