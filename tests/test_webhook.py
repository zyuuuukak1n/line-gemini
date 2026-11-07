import base64
import hashlib
import hmac
import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.main import app, line_client, gemini_client, handle_single_event
from app.line_client import LineClient, FALLBACK_ERROR_MESSAGE
from linebot.v3.webhooks import Event

client = TestClient(app)
SECRET = line_client.channel_secret


def generate_line_signature(body: str, secret: str) -> str:
    """LINEのHMAC-SHA256署名を生成するヘルパー関数"""
    hash_obj = hmac.new(
        secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    )
    return base64.b64encode(hash_obj.digest()).decode("utf-8")


def create_mock_message_event(
    text: str,
    source_type: str = "user",
    source_id: str = "U12345",
    group_id: str = None,
    mention_list: list = None,
    reply_token: str = "token_test_123",
) -> Event:
    """LINEのMessageEventモデルを生成するヘルパー"""
    source_dict = {"type": source_type}
    if source_type == "group":
        source_dict["groupId"] = group_id or "G_DEFAULT_123"
        source_dict["userId"] = source_id
    elif source_type == "room":
        source_dict["roomId"] = group_id or "R_DEFAULT_123"
        source_dict["userId"] = source_id
    else:
        source_dict["userId"] = source_id

    message_dict = {
        "type": "text",
        "id": "msg_001",
        "quoteToken": "quote_tok_001",
        "text": text,
    }
    if mention_list is not None:
        message_dict["mention"] = {"mentionees": mention_list}

    event_dict = {
        "type": "message",
        "mode": "active",
        "timestamp": 1600000000000,
        "source": source_dict,
        "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
        "deliveryContext": {"isRedelivery": False},
        "replyToken": reply_token,
        "message": message_dict,
    }
    return Event.from_dict(event_dict)


def create_mock_join_event(group_id: str = "G_JOIN_GROUP_123") -> Event:
    """LINEのJoinEventモデルを生成するヘルパー"""
    event_dict = {
        "type": "join",
        "mode": "active",
        "timestamp": 1600000000000,
        "source": {"type": "group", "groupId": group_id},
        "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
        "deliveryContext": {"isRedelivery": False},
        "replyToken": "join_token_123",
    }
    return Event.from_dict(event_dict)


def test_health_check():
    """ヘルスチェックエンドポイントの正常疎通テスト"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "line-gemini-bot"

    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert root_resp.json()["status"] == "healthy"


def test_missing_signature():
    """署名ヘッダーが存在しない場合は 400 Bad Request を返す"""
    response = client.post("/callback", json={"events": []})
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing X-Line-Signature header"


def test_invalid_signature():
    """不正な署名の場合は 400 Bad Request を返す"""
    payload = json.dumps({"events": []})
    headers = {"X-Line-Signature": "invalid_signature_value"}
    response = client.post(
        "/callback",
        content=payload,
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid signature"


def test_valid_signature_immediate_response():
    """有効な署名の場合は即座に 200 OK を返し、BackgroundTasksへ委譲する"""
    payload = json.dumps({"events": []})
    signature = generate_line_signature(payload, SECRET)
    headers = {"X-Line-Signature": signature}

    response = client.post(
        "/callback",
        content=payload,
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_extract_prompt_with_mention():
    """メンション付きテキストからメンション文字列が正確に除去されることを検証"""
    test_line = LineClient(
        channel_secret="sec",
        channel_access_token="tok",
        bot_user_id="Ubot123",
    )

    # 1. mentionees のスパン情報による除去 ("@Bot 来週のPTA出欠連絡を作って")
    event = create_mock_message_event(
        text="@Bot 来週のPTA出欠連絡を作って",
        source_type="group",
        group_id="G_123",
        mention_list=[
            {
                "type": "user",
                "index": 0,
                "length": 5,
                "userId": "Ubot123",
                "isSelf": True,
            }
        ],
    )
    extracted = test_line.extract_prompt(event.message, is_group_or_room=True)
    assert extracted == "来週のPTA出欠連絡を作って"

    # 2. 1対1トークではメンション除去を行わずそのまま
    user_event = create_mock_message_event(
        text="@Bot 来週のPTA出欠連絡を作って",
        source_type="user",
    )
    user_extracted = test_line.extract_prompt(user_event.message, is_group_or_room=False)
    assert user_extracted == "@Bot 来週のPTA出欠連絡を作って"


def test_group_mention_filter():
    """グループチャットでBotへのメンションがない日常会話は無視されることを検証"""
    test_line = LineClient(
        channel_secret="sec",
        channel_access_token="tok",
        bot_user_id="Ubot123",
    )

    # メンションなしの日常会話
    ev_no_mention = create_mock_message_event(
        text="今日の晩御飯なににする？",
        source_type="group",
        group_id="G_123",
        mention_list=None,
    )
    assert test_line.is_bot_mentioned(ev_no_mention.message) is False

    # 他人宛てのメンション
    ev_other_mention = create_mock_message_event(
        text="@Papa 今日の晩御飯なににする？",
        source_type="group",
        group_id="G_123",
        mention_list=[
            {
                "type": "user",
                "index": 0,
                "length": 6,
                "userId": "Uother456",
                "isSelf": False,
            }
        ],
    )
    assert test_line.is_bot_mentioned(ev_other_mention.message) is False

    # Bot宛てのメンション (is_self=True)
    ev_bot_mention = create_mock_message_event(
        text="@Bot 文章作って",
        source_type="group",
        group_id="G_123",
        mention_list=[
            {
                "type": "user",
                "index": 0,
                "length": 5,
                "userId": "Ubot123",
                "isSelf": True,
            }
        ],
    )
    assert test_line.is_bot_mentioned(ev_bot_mention.message) is True


def test_whitelist_access_control():
    """ホワイトリストに登録されていないグループやユーザーは拒否されることを検証"""
    allowed_line = LineClient(
        channel_secret="sec",
        channel_access_token="tok",
        allowed_group_ids={"G_ALLOWED_1", "G_ALLOWED_2"},
        allowed_user_ids={"U_ALLOWED_1"},
    )

    # 許可されたグループ
    ev_allowed_group = create_mock_message_event(
        text="test",
        source_type="group",
        group_id="G_ALLOWED_1",
    )
    allowed, s_type, s_id = allowed_line.is_source_allowed(ev_allowed_group)
    assert allowed is True
    assert s_type == "group"
    assert s_id == "G_ALLOWED_1"

    # 未許可のグループ
    ev_denied_group = create_mock_message_event(
        text="test",
        source_type="group",
        group_id="G_DENIED_999",
    )
    allowed, s_type, s_id = allowed_line.is_source_allowed(ev_denied_group)
    assert allowed is False
    assert s_type == "group"
    assert s_id == "G_DENIED_999"

    # 未許可のユーザー
    ev_denied_user = create_mock_message_event(
        text="test",
        source_type="user",
        source_id="U_DENIED_888",
    )
    allowed, s_type, s_id = allowed_line.is_source_allowed(ev_denied_user)
    assert allowed is False
    assert s_type == "user"
    assert s_id == "U_DENIED_888"


@patch.object(gemini_client, "generate_draft")
@patch.object(line_client, "reply_text")
def test_handle_single_event_success(mock_reply, mock_generate):
    """正常系: 1対1トークでメッセージを受信し、Gemini呼び出しと返信が行われること"""
    mock_generate.return_value = "学校連絡の文章です。欠席いたします。"

    event = create_mock_message_event(
        text="明日の欠席連絡を作って",
        source_type="user",
        source_id="U_USER_1",
        reply_token="reply_tok_123",
    )

    handle_single_event(event)

    mock_generate.assert_called_once_with("明日の欠席連絡を作って")
    mock_reply.assert_called_once_with("reply_tok_123", "学校連絡の文章です。欠席いたします。")


@patch.object(gemini_client, "generate_draft", side_effect=Exception("API Quota Exceeded"))
@patch.object(line_client, "reply_fallback_error")
def test_handle_single_event_error_fallback(mock_fallback, mock_generate):
    """異常系: Gemini API呼び出し失敗時にフォールバックメッセージが返信されること"""
    event = create_mock_message_event(
        text="PTA挨拶文作って",
        source_type="user",
        source_id="U_USER_1",
        reply_token="reply_tok_456",
    )

    handle_single_event(event)

    mock_generate.assert_called_once()
    mock_fallback.assert_called_once_with("reply_tok_456")


def test_join_event_logging(caplog):
    """JoinEvent時にグループIDがログに出力されること"""
    join_event = create_mock_join_event(group_id="G_FAMILY_GROUP_123")
    with caplog.at_level("INFO"):
        handle_single_event(join_event)

    assert "G_FAMILY_GROUP_123" in caplog.text
    assert "JOIN EVENT" in caplog.text
