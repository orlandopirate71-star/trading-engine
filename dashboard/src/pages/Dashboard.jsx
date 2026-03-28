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
  Globe
} from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import SystemStatus from '../components/SystemStatus'

const getTradingSession = () => {
  const utcHour = new Date().getUTCHours()
  // Forex sessions in UTC
  if (utcHour >= 22 || utcHour < 6) return { name: 'Asian', color: 'bg-purple-500', textColor: 'text-purple-400' }
  if (utcHour >= 6 && utcHour < 9) return { name: 'Tokyo', color: 'bg-pink-500', textColor: 'text-pink-400' }
  if (utcHour >= 9 && utcHour < 12) return { name: 'London', color: 'bg-blue-500', textColor: 'text-blue-400' }
  if (utcHour >= 12 && utcHour < 22) return { name: 'New York', color: 'bg-green-500', textColor: 'text-green-400' }
  return { name: 'Closed', color: 'bg-gray-500', textColor: 'text-gray-400' }
}

const StatCard = ({ title, value, icon: Icon, color, subtext }) => (
  <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
    <div className="flex items-center justify-between mb-2">
      <span className="text-gray-400 text-sm">{title}</span>
      <Icon className={color} size={20} />
    </div>
    <div className="text-2xl font-bold">{value}</div>
    {subtext && <div className="text-sm text-gray-500 mt-1">{subtext}</div>}
  </div>
)

const RecentTrade = ({ trade }) => {
  const isWin = trade.pnl > 0
  const isPending = trade.status === 'pending' || trade.status === 'approved'
  
  return (
    <Link 
      to={`/trades/${trade.id}`}
      className="flex items-center justify-between p-4 bg-gray-800 rounded-lg hover:bg-gray-750 transition-colors"
    >
      <div className="flex items-center gap-4">
        <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
          trade.direction === 'long' ? 'bg-green-900' : 'bg-red-900'
        }`}>
          {trade.direction === 'long' ? 
            <TrendingUp className="text-green-400" size={20} /> : 
            <TrendingDown className="text-red-400" size={20} />
          }
        </div>
        <div>
          <div className="font-medium">{trade.symbol}</div>
          <div className="text-sm text-gray-400">{trade.strategy_name}</div>
        </div>
      </div>
      <div className="text-right">
        {trade.status === 'closed' ? (
          <>
            <div className={`font-mono font-bold ${isWin ? 'text-green-400' : 'text-red-400'}`}>
              {isWin ? '+' : ''}{trade.pnl?.toFixed(4)}
            </div>
            <div className="text-sm text-gray-400">
              {trade.pnl_percent?.toFixed(2)}%
            </div>
          </>
        ) : (
          <div className={`flex items-center gap-2 ${
            trade.status === 'approved' ? 'text-yellow-400' : 
            trade.status === 'open' ? 'text-blue-400' : 'text-gray-400'
          }`}>
            {trade.status === 'approved' && <Clock size={16} />}
            {trade.status === 'open' && <Activity size={16} />}
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
    <div className="p-4 bg-gray-800 rounded-lg border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className={`px-2 py-1 rounded text-xs font-bold ${
            position.direction === 'long' ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400'
          }`}>
            {position.direction?.toUpperCase()}
          </div>
          <span className="font-medium">{position.symbol}</span>
          <span className={`px-2 py-0.5 rounded text-xs ${
            position.broker === 'oanda' ? 'bg-blue-900 text-blue-400' : 'bg-gray-700 text-gray-400'
          }`}>
            {position.broker === 'oanda' ? 'OANDA' : 'Paper'}
          </span>
        </div>
        <div className={`font-mono font-bold ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
          {isProfit ? '+' : ''}{position.unrealized_pnl?.toFixed(4)}
        </div>
      </div>
      <div className="text-xs text-gray-500 mb-2">{position.strategy_name}</div>
      <div className="grid grid-cols-3 gap-4 text-sm">
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
        <div className="flex gap-4 mt-3 pt-3 border-t border-gray-700 text-sm">
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

  return (
    <div className="p-6 space-y-6">
      <SystemStatus />
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <Globe size={18} className={session.textColor} />
            <span className="text-sm text-gray-400">Session:</span>
            <span className={`px-2 py-1 rounded text-sm font-medium ${session.color} text-white`}>
              {session.name}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-3 h-3 rounded-full ${status?.running ? 'bg-green-500 animate-pulse' : 'bg-gray-500'}`} />
            <span className="text-sm text-gray-400">
              {status?.running ? 'Engine Running' : 'Engine Stopped'}
            </span>
          </div>
        </div>
      </div>

      {/* OANDA Account Card - Show when OANDA is available */}
      {oandaAccount && (
        <div className="bg-gradient-to-r from-blue-900 to-blue-800 rounded-xl p-6 border border-blue-700">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-blue-700 rounded-lg flex items-center justify-center">
                <DollarSign className="text-blue-300" size={24} />
              </div>
              <div>
                <div className="text-blue-300 text-sm">OANDA Demo Account</div>
                <div className="text-2xl font-bold">
                  {oandaAccount.currency === 'GBP' ? '£' : '$'}
                  {oandaAccount.balance?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </div>
              </div>
            </div>
            <div className={`px-3 py-1 rounded-full text-sm ${
              brokerInfo?.mode === 'oanda' ? 'bg-green-600 text-white' : 'bg-gray-600 text-gray-300'
            }`}>
              {brokerInfo?.mode === 'oanda' ? 'LIVE' : 'Paper Mode'}
            </div>
          </div>
          <div className="grid grid-cols-4 gap-4 text-sm">
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
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
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
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <h2 className="text-lg font-semibold mb-4">Cumulative P&L (7 Days)</h2>
          <div className="h-64">
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Open Positions */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Activity size={20} className="text-yellow-400" />
            Open Positions
          </h2>
          {positions.length > 0 ? (
            <div className="space-y-3">
              {positions.map((pos, i) => (
                <OpenPosition key={i} position={pos} />
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              No open positions
            </div>
          )}
        </div>

        {/* Recent Trades */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Recent Trades</h2>
            <Link to="/trades" className="text-sm text-blue-400 hover:text-blue-300">
              View All →
            </Link>
          </div>
          {trades.length > 0 ? (
            <div className="space-y-2">
              {trades.slice(0, 5).map((trade) => (
                <RecentTrade key={trade.id} trade={trade} />
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              No trades yet
            </div>
          )}
        </div>
      </div>

      {/* Active Strategies */}
      <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <Target size={20} className="text-blue-400" />
          Active Strategies
        </h2>
        {status?.strategies?.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {status.strategies.map((strat) => (
              <div 
                key={strat.name}
                className={`p-4 rounded-lg border ${
                  strat.enabled 
                    ? 'border-green-700 bg-green-900/20' 
                    : 'border-gray-700 bg-gray-900/50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{strat.name}</span>
                  {strat.enabled ? (
                    <CheckCircle size={18} className="text-green-400" />
                  ) : (
                    <AlertCircle size={18} className="text-gray-500" />
                  )}
                </div>
                {strat.error && (
                  <div className="text-xs text-red-400 mt-2 truncate">
                    {strat.error}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">
            No strategies loaded. Add .py files to the strategies folder.
          </div>
        )}
      </div>
    </div>
  )
}
