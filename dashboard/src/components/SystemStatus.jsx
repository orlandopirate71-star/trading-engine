import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  Server,
  Database,
  Activity,
  Zap,
  Globe,
  RefreshCw
} from 'lucide-react'

const StatusIndicator = ({ ok, label, icon: Icon }) => (
  <div className={`flex items-center gap-2 px-4 py-2 rounded-lg ${
    ok ? 'bg-green-900/30 border border-green-700' : 'bg-red-900/30 border border-red-700'
  }`}>
    <div className={`w-3 h-3 rounded-full ${ok ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
    <Icon className={ok ? 'text-green-400' : 'text-red-400'} size={16} />
    <span className={ok ? 'text-green-400' : 'text-red-400'}>{label}</span>
  </div>
)

const SystemStatus = () => {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState(null)

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/system/status')
      const data = await res.json()
      setStatus(data)
      setLastUpdate(new Date())
    } catch (err) {
      console.error('Failed to fetch system status:', err)
      setStatus({ all_ok: false, redis: false, database: false, feed: false, engine: false, oanda: false })
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 10000) // Refresh every 10 seconds
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
        <div className="animate-pulse space-y-2">
          <div className="h-4 bg-gray-700 rounded w-1/4"></div>
          <div className="h-8 bg-gray-700 rounded w-3/4"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Server size={20} className="text-gray-400" />
          System Status
        </h2>
        <button
          onClick={fetchStatus}
          className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
          title="Refresh"
        >
          <RefreshCw size={16} className="text-gray-400" />
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-4">
        <StatusIndicator ok={status?.redis} label="Redis" icon={Zap} />
        <StatusIndicator ok={status?.database} label="Database" icon={Database} />
        <StatusIndicator ok={status?.feed} label="Feed" icon={Activity} />
        <StatusIndicator ok={status?.engine} label="Engine" icon={Server} />
        <StatusIndicator ok={status?.oanda} label="OANDA" icon={Globe} />
      </div>

      <div className="flex items-center justify-between">
        <div className={`flex items-center gap-2 px-4 py-2 rounded-lg ${
          status?.all_ok
            ? 'bg-green-900/30 border border-green-700'
            : 'bg-yellow-900/30 border border-yellow-700'
        }`}>
          <div className={`w-3 h-3 rounded-full ${
            status?.all_ok ? 'bg-green-500' : 'bg-yellow-500 animate-pulse'
          }`} />
          <span className={status?.all_ok ? 'text-green-400' : 'text-yellow-400'}>
            {status?.all_ok ? 'All Systems Operational' : 'Some Systems Issue'}
          </span>
        </div>
        {lastUpdate && (
          <span className="text-xs text-gray-500">
            Updated {lastUpdate.toLocaleTimeString()}
          </span>
        )}
      </div>

      <div className="mt-4 flex gap-2">
        <Link
          to="/logs"
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm transition-colors"
        >
          View Logs
        </Link>
      </div>
    </div>
  )
}

export default SystemStatus
