import os
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from google import genai

app = FastAPI()

# 환경 변수 로드
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# 한국어 <-> 태국어 자연스러운 구어체 번역 지시문
SYSTEM_PROMPT = """
너는 한국어와 태국어를 완벽하게 이해하는 메신저 전용 번역 시스템이야.
사용자가 입력한 문장을 다음 규칙에 맞게 번역해 줘.

[규칙]
1. 한국어가 입력되면 친근하고 자연스러운 태국어 구어체(카톡/라인 대화 스타일)로 번역한다.
2. 태국어가 입력되면 자연스러운 한국어 다정한 구어체로 번역한다.
3. 한국어 신조어, 줄임말, 오타를 문맥에 맞게 정확히 파악하여 자연스럽게 바꾼다.
4. 관용구나 속담은 현지 문화에 맞는 표현이나 자연스러운 의미 전달로 번역한다.
5. 오직 번역된 결과 문장만 출력한다. (부연 설명이나 인사말 금지)
"""

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text

    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"다음 문장을 자연스럽게 번역해줘:\n{user_text}",
            config={'system_instruction': SYSTEM_PROMPT}
        )
        translated_text = response.text.strip()
    except Exception as e:
        translated_text = "번역 중 오류가 발생했습니다."

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=translated_text)]
            )
        )