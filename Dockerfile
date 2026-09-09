FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ingest/ ingest/
COPY server/ server/
COPY web/ web/
COPY data/ingredients.json data/outcomes.json data/
COPY scripts/ scripts/

# 색인 DB 는 이미지에 넣지 않는다. 볼륨으로 붙이거나 컨테이너 안에서 수집한다.
#   docker run -v $(pwd)/data:/app/data <image> python -m ingest.build all
VOLUME /app/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
