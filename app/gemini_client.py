import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """\
あなたは、PTA役員・保護者向け連絡文、学校への提出文や連絡帳、家族・親族への連絡・相談文、お礼状・挨拶文などの実用的で丁寧な日本語文章の作成・推敲・添削に特化したプロの文章作成アシスタントです。

【絶対遵守の出力規律】
1. AI特有の前置き、挨拶、確認、補足、結びの言葉（例：「承知いたしました」「以下のように作成しました」「いかがでしょうか」「ご参考になれば幸いです」など）は一切出力しないでください。
2. 依頼者がそのままコピー＆ペーストしてLINEや連絡アプリ、メール等で即座に送信できる「実用的な完成文面」のみを出力してください。
3. 送信相手（PTA役員・保護者、学校の先生、親族、ご近所の方など）に応じた自然で適切な敬語、トーン、読みやすい改行・段落分けを自動適用してください。
4. 複数のバリエーション（例: 丁寧版、簡潔版など）が有用と思われる場合は、無駄な説明を省き【丁寧版】【簡潔版】のラベルを付けて並べて出力してください。
"""


class GeminiClient:
    """Google GenAI SDK (gemini-2.5-flash) を利用した文章生成クライアント"""

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model_name = model_name
        self._client = genai.Client(api_key=api_key)

    def generate_draft(self, prompt: str) -> str:
        """文章作成依頼をGemini APIに送り、生成された完成文面を返す

        Args:
            prompt: ユーザーからの依頼本文（メンション除去済み）

        Returns:
            str: 整形された完成文章

        Raises:
            Exception: API呼び出しや生成失敗時
        """
        logger.info("Sending request to Gemini API (model: %s, prompt length: %d)", self.model_name, len(prompt))
        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.7,
                ),
            )
            text = response.text or ""
            return text.strip()
        except Exception as e:
            logger.exception("Failed to generate content with Gemini API: %s", e)
            raise
