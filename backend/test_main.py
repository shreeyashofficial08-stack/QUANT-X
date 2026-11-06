from fastapi.testclient import TestClient
from main import app
client=TestClient(app)
def test_health():
 r=client.get('/health');assert r.status_code==200 and r.json()['status']=='ok'
 assert set(r.json()['providers'])=={'alpaca','twelve_data','india'}
def test_markets():
 r=client.get('/api/markets');assert r.status_code==200 and set(r.json())=={'INDIA','US','FOREX'}
def test_backtest():
 r=client.post('/api/backtest',json={'prices':[float(i) for i in range(1,61)],'fast_period':5,'slow_period':15});assert r.status_code==200 and len(r.json()['equity_curve'])==60
def test_paper_order():
 r=client.post('/api/paper/orders',json={'symbol':'AAPL','market':'US','side':'BUY','quantity':2,'price':100});assert r.status_code==200 and r.json()['status']=='FILLED'
