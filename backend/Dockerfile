FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY policies/ /app/policies/
EXPOSE 8000
# seed demo data on first start, then run the API
CMD ["sh", "-c", "python seed.py --if-empty && uvicorn main:app --host 0.0.0.0 --port 8000"]
