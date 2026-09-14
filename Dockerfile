FROM python:3.12-slim

WORKDIR /app

COPY mcp-server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp-server/ ./mcp-server/

WORKDIR /app/mcp-server

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "profile_store.api:app", "--host", "0.0.0.0", "--port", "8000"]
