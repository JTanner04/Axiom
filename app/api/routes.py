from fastapi import APIRouter, HTTPException, Query, Request, Response
from app.ingestion.service import ingest
from app.schemas.news import ArticleInput, ArticleRecord

router = APIRouter(prefix="/api/v1")


@router.post("/articles", response_model=ArticleRecord, status_code=201)
def create_article(article: ArticleInput, request: Request, response: Response):
    record, created = ingest(article, request.app.state.repository)
    response.status_code = 201 if created else 200
    return record


@router.get("/articles", response_model=list[ArticleRecord])
def list_articles(request: Request, limit: int = Query(50, ge=1, le=100),
                  offset: int = Query(0, ge=0)):
    return request.app.state.repository.list(limit, offset)


@router.get("/articles/{article_id}", response_model=ArticleRecord)
def get_article(article_id: str, request: Request):
    record = request.app.state.repository.get(article_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return record
