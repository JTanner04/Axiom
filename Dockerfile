FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . \
    && useradd --create-home axiom && mkdir /app/data && chown axiom:axiom /app/data
USER axiom
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
