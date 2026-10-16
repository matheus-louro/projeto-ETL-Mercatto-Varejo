FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client default-mysql-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /etl
COPY requirements.txt .
COPY requirements_diagnostico.txt .
RUN pip install --no-cache-dir -r requirements.txt -r requirements_diagnostico.txt
CMD ["sleep", "infinity"]
