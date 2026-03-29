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
      <div className="bg-gray-800 rounded-xl p-2 border border-gray-700">
        <div className="animate-pulse flex items-center gap-2">
          <div className="h-3 w-3 bg-gray-700 rounded"></div>
          <div className="h-3 bg-gray-700 rounded w-20"></div>
        </div>
      </div>
    )
  }

  const items = [
    { key: 'redis', label: 'Redis', ok: status?.redis, icon: Zap },
    { key: 'database', label: 'DB', ok: status?.database, icon: Database },
    { key: 'feed', label: 'Feed', ok: status?.feed, icon: Activity },
    { key: 'engine', label: 'Engine', ok: status?.engine, icon: Server },
    { key: 'oanda', label: 'OANDA', ok: status?.oanda, icon: Globe },
  ]

  const allOk = status?.all_ok

  return (
    <div className="bg-gray-800 rounded-xl p-2 border border-gray-700">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <div className={`w-2 h-2 rounded-full ${allOk ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
          <span className={`text-xs font-medium ${allOk ? 'text-green-400' : 'text-red-400'}`}>
            {allOk ? 'All Systems OK' : 'System Issue'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {items.map(item => (
            <div key={item.key} className="flex items-center gap-0.5" title={`${item.label}: ${item.ok ? 'OK' : 'DOWN'}`}>
              <item.icon size={10} className={item.ok ? 'text-green-500' : 'text-red-500'} />
              <span className={`text-xs ${item.ok ? 'text-green-500' : 'text-red-500'}`}>
                {item.ok ? '✓' : '✗'}
              </span>
            </div>
          ))}
          <button
            onClick={fetchStatus}
            className="p-1 hover:bg-gray-700 rounded transition-colors"
            title="Refresh"
          >
            <RefreshCw size={10} className="text-gray-400" />
          </button>
        </div>
      </div>
    </div>
  )
}

export default SystemStatus
