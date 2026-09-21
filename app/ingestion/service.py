from app.db.repository import ArticleRepository
from app.intelligence.baseline import analyze
from app.schemas.news import ArticleInput, ArticleRecord


def ingest(article: ArticleInput, repository: ArticleRepository) -> tuple[ArticleRecord, bool]:
    return repository.save(article, analyze(article))
