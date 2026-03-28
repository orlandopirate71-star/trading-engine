# Data Feed Setup Guide

You have 3 options for price feeds: **MT4**, **TradingView**, and **OANDA**.

---

## Option 1: MT4 (MetaTrader 4)

MT4 doesn't have a native API, so we use an Expert Advisor (EA) that sends prices to Python.

### Setup Steps

1. **Copy the EA code** to your MT4:
   - Open MT4 → File → Open Data Folder
   - Navigate to `MQL4/Experts/`
   - Create a new file: `PriceBridge.mq4`
   - Paste the code below

2. **Enable WebRequest in MT4**:
   - Tools → Options → Expert Advisors
   - Check "Allow WebRequest for listed URL"
   - Add: `http://localhost:5555`

3. **Attach EA to charts**:
   - Drag `PriceBridge` EA onto each chart you want to stream
   - Enable "Allow live trading" in EA settings

4. **Start the Python feed**:
   ```bash
   python multi_feed.py
   ```

### MT4 Expert Advisor Code

Save as `MQL4/Experts/PriceBridge.mq4`:

```mql4
//+------------------------------------------------------------------+
//| PriceBridge.mq4 - Sends prices to Python trading engine          |
//+------------------------------------------------------------------+
#property copyright "Trading Station"
#property version   "1.00"
#property strict

input string ServerURL = "http://localhost:5555";
input int    UpdateMS  = 100;

int OnInit()
{
   EventSetMillisecondTimer(UpdateMS);
   Print("PriceBridge started - sending to ", ServerURL);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   SendPrice();
}

void OnTick()
{
   SendPrice();
}

void SendPrice()
{
   double bid = MarketInfo(Symbol(), MODE_BID);
   double ask = MarketInfo(Symbol(), MODE_ASK);
   
   string json = StringFormat(
      "{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"time\":%d}",
      Symbol(), bid, ask, TimeCurrent()
   );
   
   string headers = "Content-Type: application/json\r\n";
   char post[];
   char result[];
   string resultHeaders;
   
   StringToCharArray(json, post);
   ArrayResize(post, ArraySize(post) - 1);
   
   int res = WebRequest("POST", ServerURL, headers, 5000, post, result, resultHeaders);
   
   if(res == -1)
   {
      int error = GetLastError();
      if(error != 4060)
         Print("WebRequest error: ", error);
   }
}
//+------------------------------------------------------------------+
```

### Config (feed_config.json)
```json
{
  "type": "mt4",
  "enabled": true,
  "port": 5555,
  "symbols": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
}
```

---

## Option 2: TradingView (Webhooks)

TradingView sends alerts via webhooks to your Python server.

### Setup Steps

1. **Start the webhook server**:
   ```bash
   python multi_feed.py
   ```
   This starts a webhook listener on port 5557.

2. **Make your server accessible** (choose one):
   - **Local network**: Use your local IP (e.g., `http://192.168.1.100:5557`)
   - **Internet**: Use ngrok for a public URL:
     ```bash
     ngrok http 5557
     ```
     This gives you a URL like `https://abc123.ngrok.io`

3. **Create TradingView Alert**:
   - Open a chart in TradingView
   - Click "Alert" (clock icon)
   - Set your condition
   - Check "Webhook URL" and enter your URL
   - Set the message to JSON format (see below)

### Alert Message Formats

**For price updates** (streams current price):
```json
{
  "type": "price",
  "symbol": "{{ticker}}",
  "price": {{close}}
}
```

**For trade signals** (triggers strategy):
```json
{
  "type": "signal",
  "symbol": "{{ticker}}",
  "action": "buy",
  "price": {{close}},
  "reason": "Your alert condition"
}
```

**With stop loss / take profit**:
```json
{
  "type": "signal",
  "symbol": "{{ticker}}",
  "action": "buy",
  "price": {{close}},
  "stop_loss": {{plot("Stop Loss")}},
  "take_profit": {{plot("Take Profit")}},
  "reason": "Strategy entry"
}
```

### Config (feed_config.json)
```json
{
  "type": "tradingview",
  "enabled": true,
  "port": 5557,
  "webhook_secret": "your_secret_key",
  "symbols": ["EURUSD", "GBPUSD", "BTCUSD"]
}
```

### Security Tip
Add a `webhook_secret` to your config and include it in alerts:
```json
{
  "secret": "your_secret_key",
  "type": "signal",
  ...
}
```

---

## Option 3: OANDA

Best quality forex data. Requires a free practice account.

### Setup Steps

1. **Create OANDA account**:
   - Go to [oanda.com](https://www.oanda.com)
   - Sign up for a free **Practice/Demo** account

2. **Get API credentials**:
   - Log into your OANDA account
   - Go to "Manage API Access" (under My Account)
   - Generate a new API token
   - Note your Account ID (shown in account details)

3. **Update config**:
   ```json
   {
     "type": "oanda",
     "enabled": true,
     "account_id": "101-001-12345678-001",
     "api_token": "your-api-token-here",
     "practice": true,
     "symbols": ["EUR_USD", "GBP_USD", "USD_JPY", "XAU_USD"]
   }
   ```

4. **Start the feed**:
   ```bash
   python multi_feed.py
   ```

### OANDA Symbol Format
Use underscores: `EUR_USD`, `GBP_USD`, `XAU_USD` (gold)

### Available Forex Pairs
Major pairs, crosses, and metals are all available:
- Majors: EUR_USD, GBP_USD, USD_JPY, USD_CHF, AUD_USD, USD_CAD, NZD_USD
- Crosses: EUR_GBP, EUR_JPY, GBP_JPY, EUR_AUD, etc.
- Metals: XAU_USD (gold), XAG_USD (silver)

---

## Running Multiple Feeds

You can run all three simultaneously! Edit `feed_config.json`:

```json
{
  "feeds": [
    {
      "type": "mt4",
      "enabled": true,
      "port": 5555,
      "symbols": ["EURUSD", "GBPUSD"]
    },
    {
      "type": "tradingview",
      "enabled": true,
      "port": 5557,
      "symbols": ["BTCUSD", "ETHUSD"]
    },
    {
      "type": "oanda",
      "enabled": true,
      "account_id": "YOUR_ID",
      "api_token": "YOUR_TOKEN",
      "practice": true,
      "symbols": ["EUR_USD", "XAU_USD"]
    }
  ]
}
```

Then run:
```bash
python multi_feed.py
```

All prices flow into the same trading engine via Redis.

---

## Quick Start

1. Edit `feed_config.json` with your preferred feed(s)
2. Run the feeds: `python multi_feed.py`
3. Run the API/engine: `python api.py`
4. Run the dashboard: `cd dashboard && npm run dev`
5. Open http://localhost:3000

---

## Troubleshooting

### MT4: "WebRequest error 4060"
- Enable WebRequest in MT4: Tools → Options → Expert Advisors
- Add `http://localhost:5555` to allowed URLs

### TradingView: Webhooks not arriving
- Check your firewall allows port 5557
- Use ngrok if behind NAT: `ngrok http 5557`
- Verify webhook URL in TradingView alert settings

### OANDA: "401 Unauthorized"
- Check your API token is correct
- Make sure `practice: true` matches your account type
- Tokens expire - generate a new one if needed

### No prices showing
- Check Redis is running: `redis-cli ping`
- Check feed output in terminal for errors
- Verify symbols match the feed's format
