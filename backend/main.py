from __future__ import annotations
import os,sqlite3
from datetime import datetime,timezone
from typing import Any
import httpx
from fastapi import FastAPI,HTTPException,Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
APP_DIR=os.path.dirname(os.path.abspath(__file__));DB_PATH=os.getenv("QUANTX_DB_PATH",os.path.join(APP_DIR,"quantx.db"))
ALPACA_KEY=os.getenv("ALPACA_API_KEY","");ALPACA_SECRET=os.getenv("ALPACA_SECRET_KEY","");TWELVE_KEY=os.getenv("TWELVE_DATA_API_KEY","")
INDIA_PROVIDER=os.getenv("INDIA_PROVIDER","unconfigured");INDIA_API_KEY=os.getenv("INDIA_API_KEY","");INDIA_API_BASE_URL=os.getenv("INDIA_API_BASE_URL","")
app=FastAPI(title="QUANT-X API",version="2.0.0",description="Multi-market research and paper-trading API.")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","http://localhost:5173").split(","),allow_credentials=False,allow_methods=["GET","POST","OPTIONS"],allow_headers=["*"])
def db():
 c=sqlite3.connect(DB_PATH);c.row_factory=sqlite3.Row;c.execute("""CREATE TABLE IF NOT EXISTS paper_orders(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,market TEXT NOT NULL,side TEXT NOT NULL,quantity REAL NOT NULL,price REAL NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'FILLED')""");c.commit();return c
class PaperOrder(BaseModel):
 symbol:str=Field(min_length=1,max_length=32);market:str=Field(pattern="^(INDIA|US|FOREX)$");side:str=Field(pattern="^(BUY|SELL)$");quantity:float=Field(gt=0,le=1000000);price:float=Field(gt=0)
class BacktestRequest(BaseModel):
 prices:list[float]=Field(min_length=30,max_length=5000);fast_period:int=Field(default=10,ge=2,le=100);slow_period:int=Field(default=30,ge=3,le=200);fee_bps:float=Field(default=5,ge=0,le=100)
async def get_json(url:str,headers:dict[str,str]|None=None,params:dict[str,Any]|None=None):
 try:
  async with httpx.AsyncClient(timeout=12) as client:
   r=await client.get(url,headers=headers,params=params);r.raise_for_status();return r.json()
 except httpx.HTTPStatusError as e:raise HTTPException(502,f"Provider returned HTTP {e.response.status_code}") from e
 except (httpx.RequestError,ValueError) as e:raise HTTPException(502,f"Provider unavailable: {type(e).__name__}") from e
def provider_status():
 return {"alpaca":{"configured":bool(ALPACA_KEY and ALPACA_SECRET),"status":"CONFIGURED" if ALPACA_KEY and ALPACA_SECRET else "DISCONNECTED","coverage":"US equities; Basic feed may be IEX-only"},"twelve_data":{"configured":bool(TWELVE_KEY),"status":"CONFIGURED" if TWELVE_KEY else "DISCONNECTED","coverage":"Forex; plan quotas and display rights apply"},"india":{"configured":bool(INDIA_API_KEY and INDIA_API_BASE_URL),"status":"CONFIGURED" if INDIA_API_KEY and INDIA_API_BASE_URL else "DISCONNECTED","provider":INDIA_PROVIDER,"coverage":"Authorized vendor adapter required"}}
@app.get("/")
def root():return {"name":"QUANT-X API","version":"2.0.0","docs":"/docs","message":"Unavailable market data is never fabricated."}
@app.get("/health")
def health():return {"status":"ok","timestamp":datetime.now(timezone.utc).isoformat(),"providers":provider_status()}
@app.get("/api/providers")
def providers():return provider_status()
@app.get("/api/markets")
def markets():return {"INDIA":[{"symbol":s,"name":n} for s,n in [("RELIANCE","Reliance Industries"),("TCS","Tata Consultancy Services"),("HDFCBANK","HDFC Bank"),("INFY","Infosys"),("NIFTY50","NIFTY 50")]],"US":[{"symbol":s,"name":n} for s,n in [("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),("SPY","S&P 500 ETF")]],"FOREX":[{"symbol":s,"name":s.replace("/"," / ")} for s in ["EUR/USD","GBP/USD","USD/JPY","USD/CHF","AUD/USD","USD/CAD","NZD/USD","USD/INR","EUR/INR","GBP/INR"]]}
@app.get("/api/quote/{market}/{symbol}")
async def quote(market:str,symbol:str):
 m=market.upper()
 if m=="US":
  if not(ALPACA_KEY and ALPACA_SECRET):raise HTTPException(503,"Alpaca is not configured.")
  d=await get_json(f"https://data.alpaca.markets/v2/stocks/{symbol.upper()}/quotes/latest",{"APCA-API-KEY-ID":ALPACA_KEY,"APCA-API-SECRET-KEY":ALPACA_SECRET},{"feed":"iex"});q=d.get("quote",{});p=(float(q.get("ap",0))+float(q.get("bp",0)))/2 if q.get("ap") and q.get("bp") else None
  return {"market":m,"symbol":symbol.upper(),"price":p,"bid":q.get("bp"),"ask":q.get("ap"),"timestamp":q.get("t"),"provider":"Alpaca","feed":"IEX","status":"PROVIDER_RESPONSE" if p else "UNAVAILABLE"}
 if m=="FOREX":
  if not TWELVE_KEY:raise HTTPException(503,"Twelve Data is not configured.")
  d=await get_json("https://api.twelvedata.com/price",params={"symbol":symbol.upper(),"apikey":TWELVE_KEY})
  if "price" not in d:raise HTTPException(502,d.get("message","No Forex quote returned"))
  return {"market":m,"symbol":symbol.upper(),"price":float(d["price"]),"timestamp":datetime.now(timezone.utc).isoformat(),"provider":"Twelve Data","status":"PROVIDER_RESPONSE"}
 if m=="INDIA":raise HTTPException(503,"Indian data vendor adapter is not configured. An authorized NSE/BSE vendor is required; no broker connection is required.")
 raise HTTPException(400,"Market must be INDIA, US, or FOREX.")
@app.get("/api/history/{market}/{symbol}")
async def history(market:str,symbol:str,interval:str=Query("1day"),outputsize:int=Query(100,ge=10,le=5000)):
 m=market.upper()
 if m=="US":
  if not(ALPACA_KEY and ALPACA_SECRET):raise HTTPException(503,"Alpaca is not configured.")
  tf={"1min":"1Min","5min":"5Min","15min":"15Min","1h":"1Hour","1day":"1Day","1week":"1Week"}.get(interval,"1Day")
  d=await get_json(f"https://data.alpaca.markets/v2/stocks/{symbol.upper()}/bars",{"APCA-API-KEY-ID":ALPACA_KEY,"APCA-API-SECRET-KEY":ALPACA_SECRET},{"timeframe":tf,"limit":outputsize,"feed":"iex"})
  return {"symbol":symbol.upper(),"market":m,"provider":"Alpaca","data":[{"timestamp":x["t"],"open":x["o"],"high":x["h"],"low":x["l"],"close":x["c"],"volume":x["v"]} for x in d.get("bars",[])]}
 if m=="FOREX":
  if not TWELVE_KEY:raise HTTPException(503,"Twelve Data is not configured.")
  d=await get_json("https://api.twelvedata.com/time_series",params={"symbol":symbol.upper(),"interval":interval,"outputsize":outputsize,"apikey":TWELVE_KEY})
  if "values" not in d:raise HTTPException(502,d.get("message","No Forex history returned"))
  return {"symbol":symbol.upper(),"market":m,"provider":"Twelve Data","data":[{"timestamp":x["datetime"],"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"]),"volume":float(x.get("volume") or 0)} for x in reversed(d["values"])]}
 if m=="INDIA":raise HTTPException(503,"Indian historical data requires an authorized vendor adapter.")
 raise HTTPException(400,"Unknown market.")
@app.get("/api/signals/{market}/{symbol}")
async def signal(market:str,symbol:str):
 data=(await history(market,symbol,"1day",100))["data"];c=[float(x["close"]) for x in data]
 if len(c)<30:raise HTTPException(422,"At least 30 candles are required.")
 f=sum(c[-10:])/10;s=sum(c[-30:])/30;mom=(c[-1]/c[-6]-1)*100 if c[-6] else 0
 action="BUY" if f>s and mom>0 else "SELL" if f<s and mom<0 else "HOLD"
 return {"symbol":symbol.upper(),"market":market.upper(),"signal":action,"method":"10/30 SMA trend plus 5-period momentum; rule-based, not trained ML","fast_sma":f,"slow_sma":s,"momentum_pct":mom,"confidence":None,"timestamp":datetime.now(timezone.utc).isoformat()}
@app.post("/api/backtest")
def backtest(req:BacktestRequest):
 if req.fast_period>=req.slow_period or len(req.prices)<=req.slow_period:raise HTTPException(422,"Fast period must be smaller than slow period.")
 cash,units,equity=1.,0.,[];trades=0
 for i,p in enumerate(req.prices):
  if i<req.slow_period:equity.append(cash+units*p);continue
  f=sum(req.prices[i-req.fast_period+1:i+1])/req.fast_period;s=sum(req.prices[i-req.slow_period+1:i+1])/req.slow_period
  if f>s and units==0:units=cash*(1-req.fee_bps/10000)/p;cash=0;trades+=1
  elif f<s and units>0:cash=units*p*(1-req.fee_bps/10000);units=0;trades+=1
  equity.append(cash+units*p)
 peak=equity[0];dd=0.
 for v in equity:peak=max(peak,v);dd=min(dd,(v/peak-1)*100 if peak else 0)
 return {"initial_capital":1.,"final_equity":equity[-1],"return_pct":(equity[-1]-1)*100,"max_drawdown_pct":dd,"trades":trades,"equity_curve":equity,"limitations":["Long-only SMA crossover","Simplified fees; no slippage, taxes or realistic fills","Chronological prices required","Past performance does not predict future returns"]}
@app.post("/api/paper/orders")
def create_order(o:PaperOrder):
 c=db()
 try:
  cur=c.execute("INSERT INTO paper_orders(symbol,market,side,quantity,price,created_at) VALUES(?,?,?,?,?,?)",(o.symbol.upper(),o.market,o.side,o.quantity,o.price,datetime.now(timezone.utc).isoformat()));c.commit();return dict(c.execute("SELECT * FROM paper_orders WHERE id=?",(cur.lastrowid,)).fetchone())
 finally:c.close()
@app.get("/api/paper/orders")
def list_orders():
 c=db()
 try:return [dict(x) for x in c.execute("SELECT * FROM paper_orders ORDER BY id DESC LIMIT 500")]
 finally:c.close()
@app.get("/api/paper/portfolio")
def portfolio():
 c=db()
 try:
  rows=c.execute("SELECT symbol,market,SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END) quantity,SUM(CASE WHEN side='BUY' THEN quantity*price ELSE -quantity*price END) cost FROM paper_orders GROUP BY symbol,market").fetchall()
  return {"positions":[dict(x) for x in rows if abs(x["quantity"])>1e-9],"note":"Virtual ledger only; live valuation and realized P&L not implemented."}
 finally:c.close()
@app.get("/api/news")
def news():return {"items":[],"status":"NOT_CONFIGURED","message":"No news provider configured; headlines are not fabricated."}
