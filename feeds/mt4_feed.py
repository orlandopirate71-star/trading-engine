"""
MT4 Feed Integration

MT4 doesn't have a native API, so we use a bridge approach:
1. Run a small EA (Expert Advisor) in MT4 that sends prices via HTTP/socket
2. This feed receives those prices

You'll need to install the MT4 EA script (provided below) in your MT4 terminal.
"""
import json
import socket
import threading
from typing import List, Callable, Optional
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from .base_feed import BaseFeed, Tick


class MT4HTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for receiving MT4 price updates."""
    
    feed: 'MT4Feed' = None
    
    def log_message(self, format, *args):
        pass  # Suppress default logging
    
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(body)
            
            # Handle tick data from MT4
            if self.feed:
                symbol = data.get("symbol", "")
                bid = float(data.get("bid", 0))
                ask = float(data.get("ask", 0))
                price = (bid + ask) / 2
                
                tick = Tick(
                    symbol=symbol.replace("/", ""),
                    price=price,
                    bid=bid,
                    ask=ask,
                    source="MT4"
                )
                self.feed.emit_tick(tick)
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
            
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())
    
    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'MT4 Feed Running')


class MT4Feed(BaseFeed):
    """
    MT4 feed that receives prices via HTTP from an MT4 Expert Advisor.
    
    Setup:
    1. Copy the EA code (see mt4_ea_code() method) into MT4
    2. Attach EA to charts you want to stream
    3. EA sends prices to this HTTP server
    """
    
    name = "MT4"
    
    def __init__(
        self, 
        symbols: List[str], 
        host: str = "0.0.0.0",
        port: int = 5555,
        on_tick: Callable[[Tick], None] = None
    ):
        super().__init__(symbols, on_tick)
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
    
    def connect(self) -> bool:
        return True
    
    def disconnect(self):
        if self.server:
            self.server.shutdown()
    
    def _run(self):
        """Run HTTP server to receive MT4 prices."""
        MT4HTTPHandler.feed = self
        
        self.server = HTTPServer((self.host, self.port), MT4HTTPHandler)
        print(f"[MT4] Listening on http://{self.host}:{self.port}")
        print(f"[MT4] Configure MT4 EA to send prices to this address")
        
        while self.running:
            self.server.handle_request()
    
    @staticmethod
    def mt4_ea_code() -> str:
        """
        Returns the MQL4 code for the Expert Advisor.
        Save this as 'PriceBridge.mq4' in MT4's Experts folder.
        """
        return '''
//+------------------------------------------------------------------+
//| PriceBridge.mq4 - Sends prices to Python trading engine          |
//+------------------------------------------------------------------+
#property copyright "Trading Station"
#property link      ""
#property version   "1.00"
#property strict

// Configuration
input string ServerURL = "http://localhost:5555";  // Python server URL
input int    UpdateMS  = 100;                       // Update interval (ms)

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
      "{\\"symbol\\":\\"%s\\",\\"bid\\":%.5f,\\"ask\\":%.5f,\\"time\\":%d}",
      Symbol(), bid, ask, TimeCurrent()
   );
   
   string headers = "Content-Type: application/json\\r\\n";
   char post[];
   char result[];
   string resultHeaders;
   
   StringToCharArray(json, post);
   ArrayResize(post, ArraySize(post) - 1);  // Remove null terminator
   
   int res = WebRequest(
      "POST",
      ServerURL,
      headers,
      5000,
      post,
      result,
      resultHeaders
   );
   
   if(res == -1)
   {
      int error = GetLastError();
      if(error != 4060)  // Ignore "no connection" spam
         Print("WebRequest error: ", error);
   }
}
//+------------------------------------------------------------------+
'''


class MT4SocketFeed(BaseFeed):
    """
    Alternative MT4 feed using raw TCP sockets (faster than HTTP).
    """
    
    name = "MT4Socket"
    
    def __init__(
        self,
        symbols: List[str],
        host: str = "0.0.0.0",
        port: int = 5556,
        on_tick: Callable[[Tick], None] = None
    ):
        super().__init__(symbols, on_tick)
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
    
    def connect(self) -> bool:
        return True
    
    def disconnect(self):
        if self.socket:
            self.socket.close()
    
    def _run(self):
        """Run socket server to receive MT4 prices."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(5)
        self.socket.settimeout(1.0)
        
        print(f"[MT4Socket] Listening on {self.host}:{self.port}")
        
        while self.running:
            try:
                conn, addr = self.socket.accept()
                threading.Thread(
                    target=self._handle_client,
                    args=(conn,),
                    daemon=True
                ).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[MT4Socket] Error: {e}")
    
    def _handle_client(self, conn: socket.socket):
        """Handle incoming MT4 connection."""
        buffer = ""
        
        try:
            while self.running:
                data = conn.recv(1024).decode('utf-8')
                if not data:
                    break
                
                buffer += data
                
                # Process complete messages (newline-delimited)
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        self._process_message(line.strip())
                        
        except Exception as e:
            print(f"[MT4Socket] Client error: {e}")
        finally:
            conn.close()
    
    def _process_message(self, message: str):
        """Process a price message from MT4."""
        try:
            # Format: SYMBOL,BID,ASK
            parts = message.split(',')
            if len(parts) >= 3:
                symbol = parts[0]
                bid = float(parts[1])
                ask = float(parts[2])
                
                tick = Tick(
                    symbol=symbol,
                    price=(bid + ask) / 2,
                    bid=bid,
                    ask=ask,
                    source="MT4"
                )
                self.emit_tick(tick)
                
        except Exception as e:
            print(f"[MT4Socket] Parse error: {e}")
    
    @staticmethod
    def mt4_ea_code() -> str:
        """Socket-based EA code (faster than HTTP)."""
        return '''
//+------------------------------------------------------------------+
//| PriceBridgeSocket.mq4 - Socket-based price bridge                |
//+------------------------------------------------------------------+
#property copyright "Trading Station"
#property version   "1.00"
#property strict

#include <socket.mqh>  // You need socket library for MQL4

input string ServerIP   = "127.0.0.1";
input int    ServerPort = 5556;
input int    UpdateMS   = 50;

int sock = INVALID_SOCKET;

int OnInit()
{
   sock = SocketCreate();
   if(sock == INVALID_SOCKET)
   {
      Print("Failed to create socket");
      return(INIT_FAILED);
   }
   
   if(!SocketConnect(sock, ServerIP, ServerPort, 5000))
   {
      Print("Failed to connect to ", ServerIP, ":", ServerPort);
      return(INIT_FAILED);
   }
   
   Print("Connected to Python server");
   EventSetMillisecondTimer(UpdateMS);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   if(sock != INVALID_SOCKET)
      SocketClose(sock);
}

void OnTimer()
{
   SendPrice();
}

void SendPrice()
{
   if(sock == INVALID_SOCKET) return;
   
   string msg = StringFormat("%s,%.5f,%.5f\\n",
      Symbol(),
      MarketInfo(Symbol(), MODE_BID),
      MarketInfo(Symbol(), MODE_ASK)
   );
   
   char data[];
   StringToCharArray(msg, data);
   SocketSend(sock, data, ArraySize(data) - 1);
}
//+------------------------------------------------------------------+
'''
