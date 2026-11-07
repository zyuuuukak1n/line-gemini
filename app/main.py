import logging
import sys
import time
from typing import List
from fastapi import FastAPI, Request, Header, BackgroundTasks, HTTPException, status
from fastapi.responses import JSONResponse
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    Event,
    MessageEvent,
    TextMessageContent,
    JoinEvent,
    GroupSource,
    RoomSource,
)

from app.config import get_settings
from app.line_client import LineClient
from app.gemini_client import GeminiClient

# ロギング設定（構造化ログ風フォーマット）
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("line_gemini_app")

app = FastAPI(
    title="LINE Gemini Family Assistant Bot",
    description="LINE Messaging APIとGemini 2.5 Flashを連携した家族向け文章作成Botバックエンド",
    version="1.0.0",
)

# クライアント初期化
line_client = LineClient(
    channel_secret=settings.LINE_CHANNEL_SECRET,
    channel_access_token=settings.LINE_CHANNEL_ACCESS_TOKEN,
    bot_user_id=settings.LINE_BOT_USER_ID,
    allowed_group_ids=settings.allowed_group_ids,
    allowed_user_ids=settings.allowed_user_ids,
)

gemini_client = GeminiClient(
    api_key=settings.GEMINI_API_KEY,
    model_name=settings.GEMINI_MODEL,
)


def handle_single_event(event: Event) -> None:
    """単一のLINE Webhookイベントを同期・安全に処理するワーカー"""
    start_time = time.time()

    # 1. グループ参加イベント (JoinEvent)
    if isinstance(event, JoinEvent):
        group_id = getattr(event.source, "group_id", None) or getattr(event.source, "room_id", None)
        logger.info("=== [JOIN EVENT] Bot joined new group/room! ID: %s ===", group_id)
        return

    # 2. メッセージイベントかつテキストメッセージ
    if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
        reply_token = event.reply_token

        # ホワイトリスト判定
        is_allowed, source_type, source_id = line_client.is_source_allowed(event)
        if not is_allowed:
            logger.warning(
                "Access rejected by whitelist. type=%s, id=%s",
                source_type,
                source_id,
            )
            return

        is_group_or_room = isinstance(event.source, (GroupSource, RoomSource))

        # グループ/ルームの場合はメンション検知
        if is_group_or_room:
            if not line_client.is_bot_mentioned(event.message):
                # メンションされていない日常会話は無視
                logger.debug("Group message received without bot mention. Ignored. (groupId=%s)", source_id)
                return

        # プロンプトの抽出（メンション除去）
        prompt = line_client.extract_prompt(event.message, is_group_or_room)
        if not prompt:
            logger.info("Mentioned with empty prompt. Sending guide message.")
            guide_msg = "文章作成のご依頼内容を入力してください。\n（例: 明日のPTA役員会の欠席連絡、学校の担任の先生への連絡帳の文面 など）"
            line_client.reply_text(reply_token, guide_msg)
            return

        logger.info(
            "Processing prompt from [%s:%s] (length: %d chars)",
            source_type,
            source_id,
            len(prompt),
        )

        # Gemini API による文章生成と返信
        try:
            gemini_start = time.time()
            draft = gemini_client.generate_draft(prompt)
            gemini_duration = time.time() - gemini_start

            logger.info(
                "Gemini generated draft in %.2fs. Sending reply to LINE...",
                gemini_duration,
            )
            line_client.reply_text(reply_token, draft)

            total_duration = time.time() - start_time
            logger.info("Successfully completed request in %.2fs total", total_duration)

        except Exception as e:
            logger.exception("Error occurred while generating or replying: %s", e)
            line_client.reply_fallback_error(reply_token)


def process_events(events: List[Event]) -> None:
    """FastAPIのBackgroundTasksで実行されるイベント群の一括ワーカー"""
    for event in events:
        try:
            handle_single_event(event)
        except Exception as e:
            logger.exception("Unhandled error processing event: %s", e)


@app.get("/health")
@app.get("/")
async def health_check():
    """死活監視・ヘルスチェック用エンドポイント"""
    return {
        "status": "healthy",
        "service": "line-gemini-bot",
        "model": settings.GEMINI_MODEL,
        "allowed_groups_count": len(settings.allowed_group_ids),
        "allowed_users_count": len(settings.allowed_user_ids),
    }


@app.post("/callback")
@app.post("/tools/line-gemini/callback")
async def webhook_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(None, alias="X-Line-Signature"),
):
    """LINEプラットフォームからのWebhookを受信するエンドポイント

    - 署名検証が成功したら即座に 200 OK を返却
    - Gemini呼び出しおよび返信処理は BackgroundTasks で非同期実行
    """
    if not x_line_signature:
        logger.warning("Missing X-Line-Signature header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Line-Signature header",
        )

    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8")

    try:
        events = line_client.parse_events(body_text, x_line_signature)
    except InvalidSignatureError:
        logger.warning("Invalid LINE signature detected")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )
    except Exception as e:
        logger.exception("Error parsing LINE webhook: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook parsing error",
        )

    # 非同期バックグラウンド処理を登録
    background_tasks.add_task(process_events, events)

    # LINEプラットフォームへ即座に応答（数秒以内のタイムアウト回避）
    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})
