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
import urllib.request
import json

app = FastAPI()

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

SYSTEM_PROMPT = """
너는 한국어와 태국어를 완벽하게 이해하는 메신저 전용 번역 시스템이야.
사용자가 입력한 문장을 다음 규칙에 따라 번역해 줘.

[규칙]
1. 한국어가 입력되면 친근하고 자연스러운 태국어 구어체(카톡/라인 대화 스타일)로 번역한다.
2. 태국어가 입력되면 자연스러운 한국어와 다양한 구어체로 번역한다.
3. 한국어의 신조어, 줄임말, 오타를 문맥에 맞게 정확히 파악하여 자연스럽게 바꾼다.
4. 관용구나 속담은 현지 문화에 맞는 표현이나 자연스러운 의미로 번역한다.
5. 오직 번역된 결과 문장만 출력한다. (부가 설명이나 인사말 금지)
"""

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {
            "contents": [{"parts": [{"text": user_message}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]}
        }
        
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            translated_text = res_data['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        translated_text = f"[번역 오류]: {str(e)}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=translated_text)]
            )
        )
