# LINE × Gemini 家族文章アシスタント デプロイガイド (汎用版)

本ガイドは、任意のLinuxサーバーまたはDocker環境に `line-gemini` をデプロイするための汎用手順書です。

---

## 1. 前提条件

- Docker および Docker Compose がインストールされていること
- 公開用のHTTPSドメインまたはトンネリングサービス（Cloudflare Tunnel, ngrok 等）
- LINE Developers アカウント（Messaging API チャネル）
- Google AI Studio API キー

---

## 2. 環境変数の設定

リポジトリ直下の `.env.example` をコピーして `.env` を作成します。

```bash
cp .env.example .env
```

`.env` 内の各項目を設定します:

```env
# LINE Messaging API
LINE_CHANNEL_SECRET=your_line_channel_secret
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
LINE_BOT_USER_ID=your_bot_user_id

# Google Gemini API
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash

# セキュリティ（ホワイトリスト・カンマ区切り）
ALLOWED_GROUP_IDS=
ALLOWED_USER_IDS=

# サーバー待受ポート
PORT=8000
LOG_LEVEL=INFO
```

---

## 3. コンテナのビルドと起動

Docker Compose を利用してビルドとバックグラウンド起動を行います。

```bash
docker compose up -d --build
```

コンテナの稼働状況を確認します:

```bash
docker compose ps
docker compose logs -f line-gemini-bot
```

---

## 4. リバースプロキシまたはトンネルの設定

コンテナは `127.0.0.1:8090` にバインドされます。外部からのHTTPSトラフィックをこのポートへリバースプロキシしてください。

### Nginx 設定例
```nginx
location /tools/line-gemini/ {
    proxy_pass http://127.0.0.1:8090/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### Apache2 設定例
```apache
<Location /tools/line-gemini/>
    ProxyPass http://127.0.0.1:8090/
    ProxyPassReverse http://127.0.0.1:8090/
</Location>
```

---

## 5. LINE Developersコンソールの設定

1. [LINE Developers Console](https://developers.line.biz/console/) にログイン。
2. 対象チャネルの「Messaging API設定」タブを開きます。
3. **Webhook URL** に公開URLを設定します:
   ```text
   https://<あなたのドメイン>/tools/line-gemini/callback
   ```
4. **「Webhookの利用」** を **オン** にします。
5. **「検証」** を実行し、Status 200 が返ることを確認します。
6. LINE Official Account Manager で「応答メッセージ」をオフ、「グループ・複数人トークへの参加」を「許可」に設定してください。

---

## 6. 死活監視・ヘルスチェック

ヘルスチェックエンドポイントへリクエストを送信して確認します:

```bash
curl -i http://127.0.0.1:8090/health
```

正常時の応答:
```json
HTTP/1.1 200 OK
{"status":"healthy","service":"line-gemini-bot","model":"gemini-2.5-flash","allowed_groups_count":0,"allowed_users_count":0}
```
