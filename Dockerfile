# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

WORKDIR /app

# ビルド依存の最小限のインストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# 実行用軽量ランナーイメージ
FROM python:3.11-slim AS runner

WORKDIR /app

# セキュリティ強化: 非rootユーザーの作成 (appuser: UID 10001)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/false -m appuser

# builderからインストール済みパッケージをコピー
COPY --from=builder /install /usr/local

# アプリケーションソースコードのコピー
COPY app ./app

# 所有権を非rootユーザーに変更
RUN chown -R appuser:appgroup /app

USER appuser

# コンテナ内部ポート
EXPOSE 8000

# 環境変数
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Uvicornサーバー起動
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
