FROM python:3.12-slim

WORKDIR /app

# Timezone (set TZ env var to override, e.g. America/New_York)
ENV TZ=America/Chicago
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev tzdata && \
    ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime && echo ${TZ} > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data && \
    mkdir -p /app/backups && \
    mkdir -p /app/ssh_keys && chmod 700 /app/ssh_keys && \
    chmod +x /app/docker-entrypoint.sh

EXPOSE 5005

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5005"]
