import csv
import io
import json
from fastapi import APIRouter, HTTPException, Request, Response
from app.evaluation.training import activate, dataset, train
from app.providers.alpaca import ProviderError
from app.schemas.news import ArticleInput
from app.schemas.workbench import ExecuteRequest, ModeRequest, RiskSettings

router = APIRouter(prefix='/api/v1/workbench')


def engine(request):
    return request.app.state.engine


@router.get('/state')
def state(request: Request):
    return engine(request).state()


@router.post('/cycle')
def cycle(request: Request):
    try:
        return engine(request).run_cycle()
    except ProviderError as exc:
        raise HTTPException(502,str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None


@router.post('/orders')
def execute(body: ExecuteRequest, request: Request):
    try:
        return engine(request).execute(body)
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None


@router.put('/settings')
def settings(body: RiskSettings, request: Request):
    return engine(request).set_preferences(body)


@router.post('/mode')
def mode(body: ModeRequest, request: Request):
    service = engine(request)
    if not service.cycle_lock.acquire(blocking=False):
        raise HTTPException(409,'Wait for the current cycle to finish before switching modes.')
    try:
        service.scope = body.mode
    finally:
        service.cycle_lock.release()
    return {'mode':service.scope}


@router.post('/events', status_code=201)
def events(body: ArticleInput, request: Request):
    service = engine(request)
    try:
        with service.store.connection(True) as db:
            count = service.ingest(db,service.scope,body)
            service.audit(db,service.scope,'ingestion',f'Manually submitted article: {count} new ticker events.')
        return {'added':count}
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None


@router.post('/models/train')
def train_model(request: Request):
    try:
        return train(engine(request))
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None


@router.post('/models/{model_id}/activate')
def activate_model(model_id: str, request: Request):
    try:
        return activate(engine(request),model_id)
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from None


@router.get('/dataset')
def export(request: Request):
    service = engine(request)
    with service.store.connection() as db:
        samples = dataset(db,service.scope)
    output = io.StringIO()
    writer = csv.DictWriter(output,fieldnames=['event_id','ticker','received','label_end','features','return','target'])
    writer.writeheader()
    for sample in samples:
        writer.writerow({**sample,'features':json.dumps(sample['features'])})
    return Response(output.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="axiom-{service.scope}-dataset.csv"'})
