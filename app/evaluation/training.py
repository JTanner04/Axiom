"""Offline, purged chronological holdout. Never trains on future features."""
import json
import time
import uuid
from app.intelligence.research import FEATURES


def dataset(db, scope):
    samples = []
    for event in db.execute('SELECT * FROM events WHERE scope=? ORDER BY received', (scope,)):
        entry = db.execute('SELECT ts,price FROM bars WHERE scope=? AND ticker=? AND ts>=? AND ts<=? ORDER BY ts LIMIT 1',
                           (scope,event['ticker'],event['received'],event['received']+4*86400)).fetchone()
        if not entry:
            continue
        exit_bar = db.execute('SELECT ts,price FROM bars WHERE scope=? AND ticker=? AND ts>=? AND ts<=? ORDER BY ts LIMIT 1',
                              (scope,event['ticker'],entry['ts']+86400,entry['ts']+4*86400)).fetchone()
        if not exit_bar or exit_bar['ts'] > time.time():
            continue
        payload = json.loads(event['payload'])
        samples.append({'event_id':event['id'], 'ticker': event['ticker'], 'received': event['received'],
                        'label_end': exit_bar['ts'], 'features': payload['features'],
                        'return': exit_bar['price']/entry['price']-1, 'target': int(exit_bar['price']>entry['price'])})
    return samples


def train(engine):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, brier_score_loss
    from sklearn.preprocessing import StandardScaler
    scope = engine.scope
    with engine.store.connection() as db:
        samples = dataset(db, scope)
    if len(samples)<60:
        raise ValueError(f'Need at least 60 events with completed 24-hour outcomes; currently {len(samples)}. Collect more data first.')
    boundary = samples[int(len(samples)*.75)]['received']
    training = [s for s in samples if s['received']<boundary and s['label_end']<boundary]
    testing = [s for s in samples if s['received']>=boundary]
    if len(training)<30 or len(testing)<15 or len({s['target'] for s in training})<2:
        raise ValueError('Need more chronological samples and both outcome classes to train.')
    scaler = StandardScaler()
    X = scaler.fit_transform([s['features'] for s in training])
    y = [s['target'] for s in training]
    model = LogisticRegression(C=.5, max_iter=1000, random_state=42).fit(X, y)
    probability = model.predict_proba(scaler.transform([s['features'] for s in testing]))[:,1]
    actual = np.array([s['target'] for s in testing])
    prediction = (probability>=.5).astype(int)
    majority = int(sum(y)>=len(y)/2)
    payload = {'feature_names': FEATURES, 'mean': scaler.mean_.tolist(), 'scale': scaler.scale_.tolist(),
               'coef': model.coef_[0].tolist(), 'intercept': float(model.intercept_[0]),
               'train_count':len(training), 'test_count':len(testing), 'purged_count': len(samples)-len(training)-len(testing),
               'accuracy':float(accuracy_score(actual,prediction)), 'baseline_accuracy':float(np.mean(actual==majority)),
               'brier_score':float(brier_score_loss(actual,probability)), 'test_start':boundary,
               'train_label_end':max(s['label_end'] for s in training), 'horizon_hours':24,
               'synthetic':scope=='demo', 'note':'Chronological holdout, purged overlapping labels. Uncalibrated probabilities; not a profitability backtest.'}
    model_id = 'logistic-'+uuid.uuid4().hex[:12]
    with engine.store.connection(True) as db:
        db.execute('INSERT INTO models VALUES (?,?,?,?,0)', (model_id,scope,time.time(),json.dumps(payload)))
        engine.audit(db,scope,'model',f'Model evaluated: {len(training)} training / {len(testing)} test events. Accuracy {payload["accuracy"]:.1%}. Manual activation required.')
    return {'id':model_id,'payload':payload}


def activate(engine, model_id):
    with engine.store.connection(True) as db:
        if model_id != 'rules-v2' and not db.execute('SELECT 1 FROM models WHERE id=? AND scope=?',(model_id,engine.scope)).fetchone():
            raise LookupError('Model not found in this data mode')
        db.execute('UPDATE models SET active=0 WHERE scope=?',(engine.scope,))
        if model_id != 'rules-v2':
            db.execute('UPDATE models SET active=1 WHERE id=?',(model_id,))
        engine.audit(db,engine.scope,'model',f'Activated {model_id} for future events. Existing predictions remain immutable.')
    return {'active':model_id}
