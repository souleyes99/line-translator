import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("line-translator")

app = FastAPI()

LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"].strip()
LINE_CHANNEL_ACCESS_TOKEN = os.environ[
    "LINE_CHANNEL_ACCESS_TOKEN"
].strip()
GOOGLE_TRANSLATE_API_KEY = os.environ[
    "GOOGLE_TRANSLATE_API_KEY"
].strip()

GOOGLE_TRANSLATE_URL = (
    "https://translation.googleapis.com/language/translate/v2"
)

handler = WebhookHandler(LINE_CHANNEL_SECRET)
configuration = Configuration(
    access_token=LINE_CHANNEL_ACCESS_TOKEN
)


def translate_text(text):
    korean_count = len(
        re.findall(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]", text)
    )
    thai_count = len(re.findall(r"[\u0e00-\u0e7f]", text))

    target = (
        "th"
        if korean_count > 0 and korean_count >= thai_count
        else "ko"
    )

    # 원문 언어는 Google이 자동으로 감지합니다.
    payload = {
        "q": text,
        "target": target,
        "format": "text",
    }

    request = urllib.request.Request(
        GOOGLE_TRANSLATE_URL,
        data=json.dumps(
            payload, ensure_ascii=False
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Goog-Api-Key": GOOGLE_TRANSLATE_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        # 키나 원문을 로그에 기록하지 않습니다.
        logger.warning("Google Translation HTTP error: %s", error.code)

        if error.code == 400:
            return "번역 요청을 처리하지 못했습니다. API 설정을 확인해주세요."
        if error.code == 401:
            return "구글 번역 API 인증에 실패했습니다. API 키를 확인해주세요."
        if error.code == 403:
            return (
                "구글 번역 API 접근이 거부되었습니다. "
                "API 키 제한, API 사용 설정, 결제 계정을 확인해주세요."
            )
        if error.code == 429:
            return "구글 번역 API 사용 한도에 도달했습니다."
        if error.code >= 500:
            return "번역 서버에 일시적인 오류가 있습니다. 다시 보내주세요."

        return f"번역 API 오류가 발생했습니다. (HTTP {error.code})"

    except (urllib.error.URLError, TimeoutError):
        return "번역 서버 연결이 지연되고 있습니다. 다시 보내주세요."

    translations = result.get("data", {}).get("translations") or []
    if not translations:
        return "번역 결과를 받지 못했습니다. 다시 보내주세요."

    translated = html.unescape(
        translations[0].get("translatedText", "")
    ).strip()

    logger.info(
        "Google Translation source=%s target=%s input_chars=%s",
        translations[0].get("detectedSourceLanguage", "unknown"),
        target,
        len(text),
    )

    return translated or "번역 결과가 비어 있습니다. 다시 보내주세요."


def split_message(text):
    chunks = []
    current = []
    units = 0

    for char in text:
        char_units = 2 if ord(char) > 0xFFFF else 1

        if units + char_units > 4500:
            chunks.append("".join(current))
            current = []
            units = 0

        current.append(char)
        units += char_units

    if current:
        chunks.append("".join(current))

    if len(chunks) > 5:
        chunks = chunks[:5]
        chunks[-1] += "\n\n[번역이 길어 일부 생략되었습니다.]"

    return chunks


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    if not text:
        return

    started = time.perf_counter()

    # LINE 이벤트 생성부터 서버 처리 시작까지의 근사 시간입니다.
    event_age = max(0, time.time() - event.timestamp / 1000)

    try:
        translated = translate_text(text)
    except Exception as error:
        logger.error(
            "Translation failed: %s",
            type(error).__name__,
        )
        translated = "번역 처리 중 오류가 발생했습니다."

    translation_seconds = time.perf_counter() - started
    reply_started = time.perf_counter()

    try:
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(text=chunk)
                        for chunk in split_message(translated)
                    ],
                )
            )

        logger.info(
            "TIMING incoming=%.2fs google=%.2fs line=%.2fs total=%.2fs",
            event_age,
            translation_seconds,
            time.perf_counter() - reply_started,
            time.perf_counter() - started,
        )

    except Exception as error:
        logger.error(
            "LINE reply failed: %s",
            type(error).__name__,
        )


@app.api_route("/", methods=["GET", "HEAD"])
def health_check():
    return {
        "status": "ok",
        "version": "google-translation-v1",
        "provider": "Google Cloud Translation Basic v2",
    }


@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("x-line-signature")
    if not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing LINE signature",
        )

    body = (await request.body()).decode("utf-8")

    try:
        await run_in_threadpool(handler.handle, body, signature)
    except InvalidSignatureError:
        raise HTTPException(
            status_code=400,
            detail="Invalid LINE signature",
        )

    return {"status": "ok"}
