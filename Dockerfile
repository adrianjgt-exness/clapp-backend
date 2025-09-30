# === Base stage: Compile, Test, and Install Dependencies ===
FROM artifactory.exness.io/golden-images/python-3.13:v9 AS base

# Set working directory
WORKDIR /app

# Copy requirements first to leverage caching
COPY requirements.txt .

# Install dependencies using JFrog Artifactory
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files
COPY . .

# Install tools needed for tests
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl unzip make \
    && rm -rf /var/lib/apt/lists/*

# === Builder stage: Development/UAT (debugging tools included) ===
FROM artifactory.exness.io/golden-images/python-3.13:v9 AS builder

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl vim unzip make \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# === Main stage: Production (minimal and secure) ===
FROM artifactory.exness.io/golden-images/python-3.13:v9 AS main

WORKDIR /app

# Copy application code and dependencies from base stage
COPY --from=base /app /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl unzip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && useradd -m appuser

# Add mongosh binary to image
RUN curl -LO https://downloads.mongodb.com/compass/mongosh-2.1.5-linux-x64.tgz \
    && tar -xzf mongosh-2.1.5-linux-x64.tgz \
    && mv mongosh-*/bin/mongosh /usr/local/bin/mongosh \
    && chmod +x /usr/local/bin/mongosh \
    && rm -rf mongosh-*

USER appuser

EXPOSE 8000

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
