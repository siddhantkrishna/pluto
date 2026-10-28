FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 pluto
COPY . .
RUN mkdir -p /app/.dev-mail && chown -R pluto:pluto /app
USER pluto
EXPOSE 8000
CMD ["uvicorn", "pluto.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
