import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.schemas.news import ArticleInput
from app.schemas.workbench import ExecuteRequest, RiskSettings
from app.trading.engine import Engine
from app.intelligence.research import extract
from app.providers.alpaca import AlpacaProvider, ProviderError
from app.evaluation.training import train, activate, dataset


@pytest.fixture
def engine(tmp_path):
    e = Engine(Settings(database_path=str(tmp_path/'ledger.db'), bootstrap_demo=False, _env_file=None))
    e.initialize()
    return e


def add_signal(engine, side='BUY', ticker='AAPL', age=0, price_age=0):
    now = time.time()
    title = 'Apple beats earnings estimates; raises guidance' if side=='BUY' else 'Apple misses earnings estimates; cuts guidance' if side=='SELL' else 'Apple announces product launch'
    article = ArticleInput(source='test',url=f'https://example.com/{time.time_ns()}',title=title,
                           published_at=datetime.fromtimestamp(now-age-60,timezone.utc),tickers=[ticker])
    with engine.store.connection(True) as db:
        engine.add_bar(db,'demo',ticker,now-price_age,100,1000)
        engine.ingest(db,'demo',article,now-age)
        return db.execute('SELECT id FROM signals ORDER BY rowid DESC LIMIT 1').fetchone()[0]


def order(engine, signal, qty=10, key=None):
    return engine.execute(ExecuteRequest(signal_id=signal,quantity=qty,request_key=key or 'key-'+str(time.time_ns())))


def test_buy_sell_costs_and_persistence(engine):
    buy = order(engine,add_signal(engine))
    assert buy['status']=='filled'
    assert buy['price_cents']==10005 and buy['fee_cents']==10
    p = engine.state()['portfolio']
    assert p['cash']==98999.4
    assert p['positions'][0]['quantity']==10
    sell = order(engine,add_signal(engine,'SELL'))
    assert sell['status']=='filled' and sell['price_cents']==9995
    p = engine.state()['portfolio']
    assert not p['positions']
    assert p['realized']==-1.2
    assert p['cash']==99998.8
    reopened = Engine(engine.settings)
    reopened.initialize()
    assert reopened.state()['portfolio']['cash']==99998.8


def test_concurrent_execution_only_fills_once(engine):
    signal = add_signal(engine)
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(lambda i: order(engine,signal,key=f'request-{i}'),range(4)))
    assert len({r['id'] for r in result})==1
    assert len(engine.state()['orders'])==1
    assert engine.state()['portfolio']['positions'][0]['quantity']==10


def test_idempotency_key_cannot_target_another_order(engine):
    one,two = add_signal(engine),add_signal(engine)
    order(engine,one,key='repeat-key')
    with pytest.raises(ValueError,match='Idempotency'):
        order(engine,two,key='repeat-key')


@pytest.mark.parametrize('case,expected', [('paused','paused'),('stale_quote','older than 15'),('stale_signal','older than 24'),('hold','HOLD'),('short','Insufficient shares'),('oversize','concentration'),('cash','cash'),('strength','strength'),('gross','exposure'),('drawdown','drawdown')])
def test_risk_rejections_do_not_mutate_cash(engine,case,expected):
    prefs = RiskSettings()
    if case=='paused': prefs.paused=True
    if case=='strength': prefs.min_strength=.99
    if case=='gross': prefs.max_gross=.05
    engine.set_preferences(prefs)
    signal = add_signal(engine,side='HOLD' if case=='hold' else 'SELL' if case=='short' else 'BUY',age=90000 if case=='stale_signal' else 0,price_age=1000 if case=='stale_quote' else 0)
    if case=='drawdown':
        with engine.store.connection(True) as db:
            db.execute("UPDATE accounts SET peak_cents=20000000 WHERE scope='demo'")
    result=order(engine,signal,qty=2000 if case=='cash' else 300 if case=='oversize' else 60 if case=='gross' else 10)
    assert result['status']=='rejected'
    assert expected.lower() in result['reason'].lower()
    assert engine.state()['portfolio']['cash']==100000
    assert not engine.state()['portfolio']['positions']


def test_modes_have_isolated_ledger_and_models(engine):
    signal=add_signal(engine)
    order(engine,signal)
    engine.scope='alpaca'
    assert engine.state()['portfolio']['cash']==100000
    assert engine.state()['events']==[]
    with pytest.raises(LookupError): order(engine,signal)
    with pytest.raises(ProviderError,match='Add AXIOM'): engine.run_cycle()


def test_future_bars_rejected_and_future_features_excluded(engine):
    now=time.time()
    with engine.store.connection(True) as db:
        engine.add_bar(db,'demo','AAPL',now-100,100,100)
        engine.add_bar(db,'demo','AAPL',now-10,200,100)
        assert extract(db,'demo','AAPL',now-50,0,.5)[2]==0
        with pytest.raises(ValueError): engine.add_bar(db,'demo','AAPL',now+60,300,100)


def test_demo_cycle_and_training(tmp_path):
    engine=Engine(Settings(database_path=str(tmp_path/'demo.db'),_env_file=None))
    engine.initialize()
    before=engine.state()['event_count']
    assert engine.run_cycle()['added']==1
    assert engine.state()['event_count']==before+1
    result=train(engine)
    model=result['payload']
    assert model['train_label_end']<model['test_start']
    assert model['synthetic'] is True and model['train_count']>=30
    assert 0<=model['accuracy']<=1 and model['test_count']>=15
    activate(engine,result['id'])
    engine.run_cycle()
    assert engine.state()['signals'][0]['model']==result['id']
    engine.scope='alpaca'
    with pytest.raises(LookupError): activate(engine,result['id'])
    with pytest.raises(ValueError,match='60 events'): train(engine)


def test_provider_contract_and_retry():
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.headers['APCA-API-KEY-ID']=='test-key'
        if len(calls)==1: return httpx.Response(429)
        if request.url.path.endswith('/news'): return httpx.Response(200,json={'news':[]})
        assert request.url.params['feed']=='iex'
        return httpx.Response(200,json={'bars':{'AAPL':{'c':100,'v':200,'t':'2026-01-01T12:00:00Z'}}})
    settings=Settings(alpaca_key='test-key',alpaca_secret='test-secret',_env_file=None)
    news,bars,truncated=AlpacaProvider(settings,transport=httpx.MockTransport(handler)).fetch(['AAPL'])
    assert len(calls)==3 and bars['AAPL']['c']==100 and not truncated


def test_api_auth_origin_validation_and_dashboard(tmp_path):
    settings=Settings(database_path=str(tmp_path/'api.db'),bootstrap_demo=False,api_token='secret',_env_file=None)
    with TestClient(create_app(settings)) as client:
        assert client.get('/').status_code==200
        assert client.get('/static/app.js').status_code==200
        assert client.get('/api/v1/workbench/state').status_code==401
        headers={'Authorization':'Bearer secret'}
        assert client.get('/api/v1/workbench/state',headers=headers).status_code==200
        assert client.post('/api/v1/workbench/cycle',headers={**headers,'Origin':'https://evil.example'}).status_code==403
        assert client.post('/api/v1/workbench/orders',headers=headers,json={'quantity':-1}).status_code==422
        assert client.post('/api/v1/workbench/mode',headers=headers,json={'mode':'live'}).status_code==422
        assert client.get('/api/v1/workbench/dataset',headers=headers).headers['content-type'].startswith('text/csv')


def test_auto_execution_respects_pause_and_reuses_keys(engine):
    signal=add_signal(engine)
    engine.set_preferences(RiskSettings(auto_execute=True,paused=True))
    engine.run_cycle()
    assert not engine.state()['orders']
    engine.set_preferences(RiskSettings(auto_execute=True))
    engine.run_cycle()
    with engine.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM orders WHERE signal_id=? AND status='filled'",(signal,)).fetchone()[0]==1
    engine.run_cycle()
    with engine.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM orders WHERE signal_id=? AND status='filled'",(signal,)).fetchone()[0]==1


def test_event_deduplication_and_no_future_publication(engine):
    now=datetime.now(timezone.utc)
    article=ArticleInput(source='test',url='https://example.com/one',title='Apple beats earnings',published_at=now,tickers=['AAPL'])
    with engine.store.connection(True) as db:
        assert engine.ingest(db,'demo',article)==1
        assert engine.ingest(db,'demo',article)==0
        assert engine.ingest(db,'alpaca',article)==1
        with pytest.raises(ValueError,match='future'):
            engine.ingest(db,'demo',article,now.timestamp()-600)


def test_workbench_submission_and_invalid_policy(tmp_path):
    config=Settings(database_path=str(tmp_path/'http.db'),bootstrap_demo=False,_env_file=None)
    with TestClient(create_app(config)) as client:
        article={'source':'test','url':'https://example.com/http','title':'Apple beats earnings','published_at':datetime.now(timezone.utc).isoformat(),'tickers':['AAPL']}
        assert client.post('/api/v1/workbench/events',json=article).json()['added']==1
        assert client.post('/api/v1/workbench/events',json=article).json()['added']==0
        state=client.get('/api/v1/workbench/state').json()
        assert state['events'][0]['ticker']=='AAPL'
        policy={**state['settings'],'max_position':2}
        assert client.put('/api/v1/workbench/settings',json=policy).status_code==422
        assert client.post('/api/v1/workbench/models/train').status_code==422
