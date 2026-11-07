import logging
import re
from typing import Optional, Tuple
from linebot.v3.webhook import WebhookParser
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    Event,
    MessageEvent,
    TextMessageContent,
    JoinEvent,
    GroupSource,
    RoomSource,
    UserSource,
)

logger = logging.getLogger(__name__)

FALLBACK_ERROR_MESSAGE = "文章の作成中にエラーが発生しました。少し時間をおいて再度お試しください。"


class LineClient:
    """LINE Messaging API (v3) の操作、署名検証、メンション検知、返信を担当するクラス"""

    def __init__(
        self,
        channel_secret: str,
        channel_access_token: str,
        bot_user_id: Optional[str] = None,
        allowed_group_ids: Optional[set[str]] = None,
        allowed_user_ids: Optional[set[str]] = None,
    ):
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token
        self.bot_user_id = bot_user_id.strip() if bot_user_id else None
        self.allowed_group_ids = allowed_group_ids or set()
        self.allowed_user_ids = allowed_user_ids or set()

        self.parser = WebhookParser(channel_secret)
        self.configuration = Configuration(access_token=channel_access_token)

    def parse_events(self, body: str, signature: str) -> list[Event]:
        """Webhookペイロードの署名を検証し、Eventリストを返す

        Raises:
            InvalidSignatureError: 署名が不正な場合
        """
        return self.parser.parse(body, signature)

    def is_source_allowed(self, event: Event) -> Tuple[bool, str, str]:
        """送信元（グループ・ルーム・ユーザー）がホワイトリストにより許可されているか判定

        Returns:
            Tuple[bool, str, str]: (許可フラグ, source_type, source_id)
        """
        source = event.source
        source_type = "unknown"
        source_id = "unknown"

        if isinstance(source, GroupSource):
            source_type = "group"
            source_id = source.group_id
            if self.allowed_group_ids and source_id not in self.allowed_group_ids:
                logger.warning(
                    "=== [ACCESS CONTROL] Access denied for unapproved group: groupId=%s ===",
                    source_id,
                )
                return False, source_type, source_id
            return True, source_type, source_id

        elif isinstance(source, RoomSource):
            source_type = "room"
            source_id = source.room_id
            if self.allowed_group_ids and source_id not in self.allowed_group_ids:
                logger.warning(
                    "=== [ACCESS CONTROL] Access denied for unapproved room: roomId=%s ===",
                    source_id,
                )
                return False, source_type, source_id
            return True, source_type, source_id

        elif isinstance(source, UserSource):
            source_type = "user"
            source_id = source.user_id
            if self.allowed_user_ids and source_id not in self.allowed_user_ids:
                logger.warning(
                    "=== [ACCESS CONTROL] Access denied for unapproved user: userId=%s ===",
                    source_id,
                )
                return False, source_type, source_id
            return True, source_type, source_id

        return True, source_type, source_id

    def is_bot_mentioned(self, text_content: TextMessageContent) -> bool:
        """グループ/ルーム内のメッセージにBotへのメンションが含まれているか判定"""
        mention = getattr(text_content, "mention", None)
        if not mention:
            return False

        mentionees = getattr(mention, "mentionees", None)
        if not mentionees:
            return False

        # mentionees リストの検証
        for m in mentionees:
            is_self = getattr(m, "is_self", False)
            user_id = getattr(m, "user_id", None)

            # LINE platform が is_self=True を付与している場合
            if is_self:
                return True

            # 設定値に bot_user_id があり、一致する場合
            if self.bot_user_id and user_id == self.bot_user_id:
                return True

        # bot_user_id が未指定で is_self も False の場合、メンションが存在すれば対象とみなす（家族グループ運用向け）
        if not self.bot_user_id:
            return True

        return False

    def extract_prompt(self, text_content: TextMessageContent, is_group_or_room: bool) -> str:
        """メッセージからメンション文字列をトリム・除去し、Geminiに渡す純粋な依頼文章を抽出"""
        raw_text = text_content.text or ""
        if not is_group_or_room:
            return raw_text.strip()

        cleaned_text = raw_text
        mention = getattr(text_content, "mention", None)
        mentionees = getattr(mention, "mentionees", None) if mention else None

        if mentionees:
            # メンション部分のインデックス（index, length）を取得し、後方から削除して位置ずれを防止
            spans: list[Tuple[int, int]] = []
            for m in mentionees:
                idx = getattr(m, "index", None)
                length = getattr(m, "length", None)
                if idx is not None and length is not None:
                    spans.append((idx, idx + length))

            spans.sort(key=lambda s: s[0], reverse=True)
            for start, end in spans:
                cleaned_text = cleaned_text[:start] + cleaned_text[end:]

        # 正規表現による先頭メンション（例: @Bot名 ）の念のためのクリーンアップ
        cleaned_text = re.sub(r"^@\S+\s*", "", cleaned_text)
        return cleaned_text.strip()

    def reply_text(self, reply_token: str, message: str) -> None:
        """LINE Messaging API を使ってテキスト返信を送信"""
        try:
            with ApiClient(self.configuration) as api_client:
                messaging_api = MessagingApi(api_client)
                messaging_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=message)],
                    )
                )
            logger.info("Successfully sent reply message (reply_token: %s...)", reply_token[:8])
        except Exception as e:
            logger.exception("Failed to send LINE reply: %s", e)
            raise

    def reply_fallback_error(self, reply_token: str) -> None:
        """エラー時のフォールバックメッセージを安全に返信"""
        try:
            self.reply_text(reply_token, FALLBACK_ERROR_MESSAGE)
        except Exception as e:
            logger.exception("Failed to send fallback error reply: %s", e)
