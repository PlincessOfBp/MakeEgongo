# -*- coding: utf-8 -*-
"""캐릭터 외관 이미지 자동 생성 파이프라인.

- 프롬프트 작성: Gemini(텍스트)가 외관+세계관에서 필요한 시각 정보만 추출해
  공식 프롬프트를 작성한다. Gemini 중단/할당량 초과 시 폴백 템플릿을 쓴다.
- 이미지 생성: Pollinations.ai(gen.pollinations.ai)를 호출한다. POLLIN_API_KEY로 인증.
- 저장: content/images/characters/{id}/appearance_v{N}.<ext>
  + 같은 이름의 .prompt.json(메타) / .prompt.txt(재사용용 프롬프트만)
- 외관 버전 관리: characters.json 의 appearance_images 배열에 버전/해시/사유를 기록.
  현재 외관 해시가 최신 버전과 같으면 생성하지 않는다(외관 변화 감지).
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
IMAGE_DIR = CONTENT / "images" / "characters"

GEN_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

STYLE_JP = (
    "modern Japanese otaku anime 2D character illustration, "
    "clean crisp lineart, anime cel-shading, clear silhouette, natural anime body proportions, "
    "not photorealistic"
)

DEFAULT_IMAGE_MODELS = [
    "pixai",
    "black-forest-labs/flux.1-schnell",
    "sana",
]


def log(msg):
    print(msg, flush=True)


# ---------- 환경 ----------


def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip("\"'")
        if k and k not in os.environ:
            os.environ[k] = v


def get_gemini_key():
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def get_pollin_key():
    return (os.environ.get("POLLIN_API_KEY") or "").strip()


def get_pixai_key():
    return (os.environ.get("PIXAI_API_KEY") or "").strip()


def get_pixai_mode():
    return (os.environ.get("PIXAI_MODE") or "standard").strip().lower()


def get_pixai_style():
    return (os.environ.get("PIXAI_STYLE") or "").strip()


def get_pixai_negative():
    return (
        os.environ.get("PIXAI_NEGATIVE")
        or "lowres, bad anatomy, bad hands, extra fingers, missing fingers, deformed, blurry, "
        "watermark, text, logo, jpeg artifacts"
    ).strip()


def get_gemini_models():
    raw = (os.environ.get("GEMINI_MODELS") or "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
        if models:
            return models
    return ["gemini-3.1-flash-lite", "gemini-3.1-flash"]


def get_image_models():
    raw = (os.environ.get("POLLIN_MODELS") or "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
        if models:
            return models
    return list(DEFAULT_IMAGE_MODELS)


def load_json(name):
    return json.loads((CONTENT / name).read_text(encoding="utf-8"))


def save_json(name, data):
    path = CONTENT / name
    raw = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(raw, encoding="utf-8", newline="\n")


def today():
    return datetime.now(timezone.utc).date().isoformat()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ApiError(Exception):
    def __init__(self, message, rotate=False):
        super().__init__(message)
        self.rotate = rotate


# ---------- 외관 해시 / 변경 감지 ----------


def appearance_hash(appearance):
    raw = json.dumps(appearance or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def current_hash(char):
    return appearance_hash(char.get("appearance") or {})


def latest_version(char):
    imgs = char.get("appearance_images") or []
    return imgs[-1] if imgs else None


def needs_image(char):
    app = char.get("appearance") or {}
    if not app:
        return False
    latest = latest_version(char)
    if not latest:
        return True
    return latest.get("appearance_hash") != current_hash(char)


# ---------- Gemini 프롬프트 작성 ----------


def call_gemini_text(model, key, prompt):
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        GEN_API_ENDPOINT.format(model=model),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        snippet = (e.read().decode("utf-8", "ignore") or "")[:300]
        low = snippet.lower()
        if e.code in (429, 404, 500, 503):
            raise ApiError(f"{model} HTTP {e.code}: {snippet}", rotate=True)
        if e.code in (400, 403):
            if "api key" in low or "api_key" in low or "invalid" in low:
                raise ApiError(f"API 키 오류 ({model}) HTTP {e.code}: {snippet}", rotate=False)
            raise ApiError(f"{model} HTTP {e.code}: {snippet}", rotate=True)
        raise ApiError(f"{model} HTTP {e.code}: {snippet}", rotate=False)
    except urllib.error.URLError as e:
        raise ApiError(f"{model} 연결 오류: {e}", rotate=True)
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise ApiError(f"{model} 응답 형식 오류: " + json.dumps(body, ensure_ascii=False)[:300])
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                raise ApiError(f"{model} JSON 파싱 실패: " + text[:200])
        raise ApiError(f"{model} JSON 파싱 실패: " + text[:200])


def appearance_block(a):
    lines = []
    for key in [
        "hair", "eyes", "skin", "face", "outfit", "shoes",
        "accessories", "belongings", "vibe", "casual", "world_trait", "notes",
    ]:
        val = a.get(key)
        if val:
            lines.append(f"- {key}: {val}")
    if a.get("traits"):
        lines.append("- traits: " + " · ".join(str(x) for x in a["traits"]))
    if a.get("colors"):
        lines.append("- colors: " + " · ".join(str(x) for x in a["colors"]))
    return "\n".join(lines) or "(없음)"


def base_info_block(c):
    return "\n".join(
        f"- {k}: {v}"
        for k, v in [
            ("name", c.get("name")),
            ("romanized", c.get("romanized")),
            ("age", c.get("age")),
            ("gender", c.get("gender")),
            ("species", c.get("species")),
            ("role", c.get("role")),
        ]
        if v
    )


def build_pixai_prompt(char, world, prev_appearance):
    """PixAI(Tsubaki 계열)에 최적화된 danbooru 태그형 프롬프트 요청 지시문."""
    w = world
    lines = []
    lines.append("너는 danbooru 태그 스타일의 애니메이션 이미지 프롬프트 작성자다.")
    lines.append("PixAI의 Tsubaki 계열 이미지 모델이 사용할 태그형 영문 프롬프트를 작성한다.")
    lines.append("다음 규칙을 지킨다.")
    lines.append("1. 태그는 콤마(,)로 구분한다. 소문자로 작성한다. 예: 1girl, long hair, blue eyes, white dress")
    lines.append("2. 캐릭터의 헤어스타일/색, 눈 색, 복장, 액세서리, 나이, 전속감 등 외관 설정을 정확한 태그로 반환한다.")
    lines.append("3. quiz 및 캐릭터 종류 태그로 1girl/1boy/solo 를 붙인다. 부분클로즈업이 아니라 전신(whole body)을 요구한다.")
    lines.append("4. 품질 태그를 맨 앞에 붙인다: masterpiece, best quality, extremely detailed")
    lines.append("5. 배경 태그: plain background, simple background, white background")
    lines.append("6. 세계관 영향이 외관에 존재하면 (고딕, 스팀펑크, 사이버펑크 등) 관련 태그를 붙인다.")
    lines.append("7. 설정에 없는 세부 요소를 추가하지 않는다. 외관을 임의로 미화하지 않는다.")
    lines.append("8. negative는 작성하지 않는다. 프롬프트만 만든다.")
    lines.append("")
    lines.append("## 캐릭터 기본 정보")
    lines.append(base_info_block(char))
    lines.append("")
    lines.append("## 현재 외관 설정")
    lines.append(appearance_block(char.get("appearance") or {}))
    lines.append("")
    if prev_appearance:
        lines.append("## 이전 외관 (이 요소는 유지하되, 변경 사항만 반영)")
        lines.append(appearance_block(prev_appearance))
        lines.append("")
    lines.append("## 세계관의 시각적 요인 (외관에 영향을 주는 경우에만)")
    for s in [f"- 시대/기술 수준: {w.get('era', '')} / {w.get('tech_level', '')}", f"- 사회적 분위기: {w.get('mood', '')}"]:
        lines.append(s)
    lines.append("")
    lines.append('다음 JSON만 반환한다: {"prompt": "<태그형 영문 프롬프트, 콤마 구분>"}')
    return "\n".join(lines)


def build_gen_prompt(char, world, prev_appearance, style="flux"):
    """이미지 생성 모델용 영문 프롬프트 요청 지시문을 만든다.

    style='pixai': danbooru 태그형 프롬프트 (PixAI/Tsubaki 계열에 유리).
    style 그 외: 자연어 문장형 (flux/sana 등 Pollinations 계열 기본).
    """
    w = world
    if style == "pixai":
        return build_pixai_prompt(char, world, prev_appearance)
    lines = []
    lines.append("너는 캐릭터 디자인 시트용 이미지 프롬프트 작성자다.")
    lines.append("캐릭터의 텍스트 설정과 세계관의 시각적 정보를 바탕으로, ")
    lines.append("이미지 생성 모델이 캐릭터 외관을 정확히 재현하도록 하는 영문 프롬프트를 작성한다.")
    lines.append("다음 규칙을 지킨다.")
    lines.append("1. 목적은 캐릭터 디자인 시트/턴어라운드. 같은 캐릭터의 정면, 측면, 후면이 한 장에 나란히 보이게 한다.")
    lines.append("2. 그림체는 현대 일본 오타쿠 애니메이션풍 2D 일러스트. 깔끔한 선화, 셀 셰이딩, 명확한 실루엣.")
    lines.append("3. 배경은 단색(흰색 또는 매우 밝은 회색). 불필요한 연출이나 소품을 넣지 않는다.")
    lines.append("4. 설정에 없는 세부 요소를 추가하지 않고, 외관을 임의로 미화하지 않는다.")
    lines.append("5. 프롬프트는 영문으로 작성한다. 캐릭터 설정은 사실 그대로 반영한다.")
    lines.append("")
    lines.append("## 캐릭터 기본 정보")
    lines.append(base_info_block(char))
    lines.append("")
    lines.append("## 현재 외관 설정")
    lines.append(appearance_block(char.get("appearance") or {}))
    lines.append("")
    if prev_appearance:
        lines.append("## 이전 외관 (이 요소는 유지하되, 다음 변경 사항만 반영)")
        lines.append(appearance_block(prev_appearance))
        lines.append("")
    lines.append("## 세계관의 시각적 요인 (외관에 영향을 주는 경우에만)")
    for s in [f"- 시대/기술 수준: {w.get('era', '')} / {w.get('tech_level', '')}", f"- 사회적 분위기: {w.get('mood', '')}"]:
        lines.append(s)
    lines.append("")
    lines.append("다음 JSON만 반환한다: {\"prompt\": \"<생성용 영문 프롬프트>\"}")
    return "\n".join(lines)


def make_prompt_with_gemini(char, world, prev_appearance, style="flux"):
    key = get_gemini_key()
    models = get_gemini_models()
    if not key:
        return None, None
    prompt = build_gen_prompt(char, world, prev_appearance, style=style)
    errors = []
    for m in models:
        for attempt in range(3):
            try:
                data = call_gemini_text(m, key, prompt)
                raw = (data or {}).get("prompt") or ""
                p = re.sub(r"\s+", " ", raw).strip()
                if len(p) > 30:
                    log(f"    프롬프트 작성 모델: {m}")
                    return p, m
                errors.append(f"{m}: 프롬프트가 너무 짧음")
                break
            except ApiError as e:
                if not e.rotate:
                    log(f"    프롬프트 작성 실패({m}): {e} → 템플릿 사용")
                    return None, None
                if attempt < 2:
                    log(f"    프롬프트 모델 {m} 일시 실패({attempt + 1}/3): {str(e)[:60]}… 재시도")
                    time.sleep(3 + attempt * 3)
                    continue
                errors.append(str(e))
                log(f"    프롬프트 모델 {m} 사용 불가 → 다음 모델")
    log("    Gemini 프롬프트 작성 실패 (" + "; ".join(errors) + ") → 템플릿 사용")
    return None, None


# 외관 키워드 → PixAI danbooru 태그 매핑 (영문, 소문자)
PIXAI_TAG_MAP = {
    "hair": ["hair", "hairstyle"],
    "eyes": ["eyes", "eye color"],
    "skin": ["skin", "complexion"],
    "face": ["face"],
    "outfit": ["outfit", "clothes", "dress"],
    "shoes": ["shoes", "footwear"],
    "accessories": ["accessory", "accessories"],
    "belongings": ["prop", "item"],
}

# 외관 값에서 발라낼 한글 잡음 키워드 등은 그대로 두고,
# 값이 짧은(외관 토큰으로 쓰일) 항목만 태그 후보로 취급한다.
PIXAI_TAG_PHRASES = {
    "red": ["red", "red_hair", "red_eyes"],
    "blue": ["blue", "blue_hair", "blue_eyes"],
    "black": ["black", "black_hair", "black_eyes"],
    "white": ["white", "white_hair"],
    "blonde": ["blonde", "blonde_hair", "yellow_hair"],
    "brown": ["brown", "brown_hair"],
    "green": ["green", "green_eyes"],
    "gray": ["gray", "grey", "gray_hair"],
    "grey": ["grey", "gray", "gray_hair"],
    "silver": ["silver", "silver_hair", "white_hair"],
    "purple": ["purple", "purple_hair", "purple_eyes"],
    "pink": ["pink", "pink_hair", "pink_eyes"],
    "long hair": ["long_hair"],
    "short": ["short_hair"],
    "단발": ["short_hair"],
    "장발": ["long_hair"],
    "포니테일": ["ponytail"],
    "빗겨 묶음": ["side_ponytail"],
    "눈": ["eyes"],
    "머리카락": ["hair"],
}


def _arange_to_tags(val):
    """외관 항목 값(문자열/리스트) → 후보 태그 문자열 목록.

    짧은 값(≤24자)은 그대로 태그로 쓰고, 긴 문장은 조각을 잘라 키워드를
    추출한다. 값에 한글이 많으면 기본 영문 태그품질 태그만 남긴다.
    """
    if isinstance(val, list):
        vals = [str(x) for x in val]
    else:
        vals = [str(val)]
    out = []
    for v in vals:
        v = re.sub(r"\s+", " ", v.strip())
        if not v:
            continue
        if len(v) <= 24:
            # 영문이면 그대로 태그, 비영문 리터럴은 생략(태그화 불가)
            if re.fullmatch(r"[a-zA-Z0-9 _\-/]+", v):
                out.append(v.lower())
            continue
        # 긴 설명 → 알려진 키워드/색상만 추출
        low = v.lower()
        for phrase, tags in PIXAI_TAG_PHRASES.items():
            if phrase in low:
                out.extend(tags)
    return out


def fallback_prompt_pixai(char, world):
    """PixAI용 fallback: 영문 danbooru 태그 + 한글 외관 설명(중복 포함).

    Gemini 실패 시에도 캐릭터 외관 정보를 잃지 않도록, 한글 설명 텍스트를
    그대로 포함한다. PixAI(또는 사용자)가 조정 가능.
    """
    a = char.get("appearance") or {}
    tags = []
    gender = "1girl" if (char.get("gender") or "").lower() in ("여", "여성", "female", "girl", "f") else "1boy"
    tags.extend([gender, "solo", "whole body", "masterpiece", "best quality", "plain background"])
    seen = set()
    uniq = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    # 영문 태그 후보 추가
    for key in ("hair", "eyes", "skin", "face", "outfit", "shoes", "accessories", "belongings"):
        val = a.get(key)
        if val:
            for t in _arange_to_tags(val):
                if t not in seen:
                    seen.add(t)
                    uniq.append(t)
    for c in (a.get("colors") or []):
        for t in _arange_to_tags(c):
            if t not in seen:
                seen.add(t)
                uniq.append(t)
    for t in (a.get("traits") or []):
        for x in _arange_to_tags(t):
            if x not in seen:
                seen.add(x)
                uniq.append(x)
    base = ", ".join(uniq)
    # 한글 외관 설명 첨부 (정보 손실 방지 — PixAI에서 조정 가능)
    desc_parts = []
    for key in ("hair", "eyes", "skin", "face", "outfit", "shoes", "accessories"):
        v = a.get(key)
        if v and isinstance(v, str) and v not in base:
            desc_parts.append(v)
    if desc_parts:
        return base + ", " + "; ".join(desc_parts)
    return base


def fallback_prompt(char, world):
    a = char.get("appearance") or {}
    chunks = []
    chunks.append(f"character design sheet turnaround of {char.get('name') or char.get('romanized')}, ")
    sub = []
    for key in ["hair", "eyes", "skin", "face", "outfit", "shoes", "accessories", "belongings"]:
        if a.get(key):
            sub.append(f"{key}: {a[key]}")
    if a.get("traits"):
        sub.append("traits: " + " · ".join(str(x) for x in a["traits"]))
    if a.get("colors"):
        sub.append("main colors: " + " / ".join(str(x) for x in a["colors"]))
    chunks.append(" ".join(sub))
    if a.get("vibe"):
        chunks.append("mood: " + str(a["vibe"]))
    chunks.append("front view, side view, back view on one sheet, the same character across all three views")
    chunks.append("plain light background")
    chunks.append(STYLE_JP)
    return " ".join(chunks)


# ---------- Pollinations 호출 ----------


def call_pollinations(prompt_text, model, width, height):
    url = "https://gen.pollinations.ai/image/" + urllib.parse.quote(prompt_text)
    url += f"?model={urllib.parse.quote(model)}&width={width}&height={height}&nologo=true"
    headers = {"User-Agent": "Mozilla/5.0"}
    key = get_pollin_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=420) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        snippet = (e.read().decode("utf-8", "ignore") or "")[:400]
        rotate = e.code in (429, 500, 502, 503)
        raise ApiError(f"{model} HTTP {e.code}: {snippet}", rotate=rotate)


# ---------- PixAI 호출 (비동기 태스크) ----------

PIXAI_API = "https://api.pixai.art"
PIXAI_POLL_INTERVAL = 3
PIXAI_POLL_TIMEOUT = 600

# PixAI 해상도 매핑 (aspectRatio + size tier → 실제 픽셀)
PIXAI_RESOLUTIONS = {
    "1:1": {"1k": (1024, 1024), "1.5k": (1536, 1536)},
    "2:3": {"1k": (848, 1280), "1.5k": (1024, 1536)},
    "3:2": {"1k": (1280, 848), "1.5k": (1536, 1024)},
    "3:4": {"1k": (864, 1152), "1.5k": (1152, 1536)},
    "4:3": {"1k": (1152, 864), "1.5k": (1536, 1152)},
    "3:5": {"1k": (768, 1280), "1.5k": (912, 1536)},
    "5:3": {"1k": (1280, 768), "1.5k": (1536, 912)},
    "9:16": {"1k": (720, 1280), "1.5k": (864, 1536)},
    "16:9": {"1k": (1280, 720), "1.5k": (1536, 864)},
    "1:3": {"1k": (512, 1536), "1.5k": (512, 1536)},
    "3:1": {"1k": (1536, 512), "1.5k": (1536, 512)},
}


def pixai_aspect_ratio(width, height):
    """원하는 w×h에 가장 가까운 PixAI 비율 매핑키(예: '5:3')를 고른다."""
    target = (width or 1024) / (height or 1024)
    best, best_d = "1:1", 1e9
    for key in PIXAI_RESOLUTIONS:
        a, _, b = key.partition(":")
        d = abs((int(a) / int(b)) - target)
        if d < best_d:
            best, best_d = key, d
    return best


def _pixai_request(path, payload, key):
    req = urllib.request.Request(
        PIXAI_API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        snippet = (e.read().decode("utf-8", "ignore") or "")[:400]
        raise ApiError(f"PixAI POST {path} HTTP {e.code}: {snippet}", rotate=False)


def _pixai_get(path, key):
    req = urllib.request.Request(
        PIXAI_API + path,
        headers={"Authorization": f"Bearer {key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        snippet = (e.read().decode("utf-8", "ignore") or "")[:400]
        raise ApiError(f"PixAI GET {path} HTTP {e.code}: {snippet}", rotate=False)


def _pixai_model_version(model_token):
    """'pixai' 접두 뒤의 셋업: 기본 모델버전 id를 환경변수에서 읽는다.

    모델 토큰 예: 'pixai' → PIXAI_MODEL_VERSION, 'pixai:TSUB_ID' → TSUB_ID 직접 사용.
    리턴: (model_version_id 또는 None)
    """
    token = model_token.split(":", 1)[1].strip() if ":" in model_token else ""
    if token:
        return token
    env_v = (os.environ.get("PIXAI_MODEL_VERSION") or "").strip()
    return env_v or None


def call_pixai(prompt_text, model, width, height):
    """PixAI 태스크 생성 → 폴링 → 완료 이미지 바이트를 리턴한다.

    PixAI는 rgapi/tsubaki 계열 애니 특화 모델로 고품질 일러스트에 적합하다.
    """
    key = get_pixai_key()
    if not key:
        raise ApiError("PIXAI_API_KEY가 없어 PixAI를 사용할 수 없음", rotate=True)
    mv = _pixai_model_version(model)
    if not mv:
        raise ApiError("PIXAI_MODEL_VERSION 미설정 (모델 버전 id 필요)", rotate=True)

    ratio = pixai_aspect_ratio(width, height)
    size = "1.5k" if max(width or 0, height or 0) > 1100 else "1k"
    payload = {
        "modelVersionId": mv,
        "prompt": prompt_text,
        "negativePrompt": get_pixai_negative(),
        "aspectRatio": ratio,
        "size": size,
        "mode": get_pixai_mode(),
        "batchSize": 1,
        "promptHelper": "disable",
    }
    style = get_pixai_style()
    if style:
        payload["style"] = {"presetName": style}

    log(f"    [pixai] 태스크 생성: model={mv} ratio={ratio} size={size} mode={get_pixai_mode()}")
    task = _pixai_request("/v2/image/create", payload, key)
    task_id = task.get("id")
    if not task_id:
        raise ApiError("PixAI 태스크 생성 응답에 id 없음", rotate=True)

    waited = 0
    while waited < PIXAI_POLL_TIMEOUT:
        time.sleep(PIXAI_POLL_INTERVAL)
        waited += PIXAI_POLL_INTERVAL
        t = _pixai_get(f"/v1/task/{task_id}", key)
        status = t.get("status", "")
        if status == "completed":
            outs = t.get("outputs") or {}
            urls = outs.get("mediaUrls") or []
            if not urls:
                mids = outs.get("mediaIds") or []
                for mid in mids:
                    m = _pixai_get(f"/v1/media/{mid}", key)
                    for u in m.get("urls") or []:
                        urls.append(u.get("url"))
            if not urls:
                raise ApiError("PixAI 태스크 완료지만 mediaUrls 없음", rotate=True)
            with urllib.request.urlopen(urls[0], timeout=120) as resp:
                return resp.read()
        if status in ("failed", "cancelled", "error"):
            raise ApiError(f"PixAI 태스크 {status}: {str(t)[:300]}", rotate=True)
        if waited % 30 == 0:
            log(f"    [pixai] 대기 중… {waited}s (status={status})")
    raise ApiError(f"PixAI 태스크 폴링 타임아웃 ({PIXAI_POLL_TIMEOUT}s)", rotate=True)


def guess_ext(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpg"
    return "bin"


def pollinations_image(char, world, width, height):
    """외관 기준 이미지 1장을 생성한다. (리턴=바이트, 프롬프트, 이미지 모델, 프롬프트 작성 모델)

    모델 풀 첫 항목이 pixai면 태그형 프롬프트(tags), 그 외 Pollinations용
    자연어 프롬프트 어느 쪽을 쓸지는 첫 성공 모델에 맞춘다.
    pixai가 1순위면 pixai 스타일 프롬프트로 생성하고, pixai 실패 시
    자연어 프롬프트로 flux/sana를 시도한다(두 콘텐츠를 모두 만들어 대비).
    """
    prev = latest_version(char)
    prev_appearance = None
    if prev:
        pj = IMAGE_DIR / char["id"] / prev.get("prompt_json", "")
        if pj.exists():
            try:
                meta = json.loads(pj.read_text(encoding="utf-8"))
                prev_appearance = meta.get("appearance") or {}
            except (ValueError, OSError):
                pass
    if not width or not height:
        width, height = 1024, 1024
    models = get_image_models()

    # 1) pixai가 1순위면 태그형 프롬프트를 만든다.
    pixai_first = any(m == "pixai" or m.startswith("pixai:") for m in models)
    errors = []

    if pixai_first:
        pt, gmodel = make_prompt_with_gemini(char, world, prev_appearance, style="pixai")
        if pt is None:
            pt = fallback_prompt_pixai(char, world)
            gmodel = "fallback-pixai-tags"
        try:
            data = call_pixai(pt, models[0], width, height)
            if len(data) < 1000:
                raise ApiError(f"{models[0]} 응답이 너무 작음({len(data)} bytes)")
            log(f"    이미지 생성 모델: {models[0]} · {len(data)} bytes · size={width}x{height} (api=pixai)")
            return data, pt, models[0], gmodel
        except ApiError as e:
            errors.append(str(e))
            suffix = " → flux/sana 폴백" if e.rotate else ""
            log(f"    이미지 모델 {models[0]} 실패: {e}{suffix}")

    # 2) 폴백: Pollinations 자연어 프롬프트
    pt, gmodel = make_prompt_with_gemini(char, world, prev_appearance, style="flux")
    if pt is None:
        pt = fallback_prompt(char, world)
        gmodel = "fallback-template"
    for m in models:
        if m == "pixai" or m.startswith("pixai:"):
            continue
        try:
            data = call_pollinations(pt, m, width, height)
            if len(data) < 1000:
                raise ApiError(f"{m} 응답이 너무 작음({len(data)} bytes)")
            log(f"    이미지 생성 모델: {m} · {len(data)} bytes · size={width}x{height} (api={m})")
            return data, pt, m, gmodel
        except ApiError as e:
            errors.append(str(e))
            log(f"    이미지 모델 {m} 실패: {e}" + (" → 다음 모델" if e.rotate else ""))
    raise ApiError("이미지 모델 모두 실패: " + " | ".join(errors))


def build_prompt_meta(char, version, prompt_text, gemini_model, image_model, width, height, reason, prev):
    gen = "pixai-api" if (image_model or "").startswith("pixai") else "pollinations-gen"
    return {
        "version": version,
        "created_at": now_iso(),
        "generator": gen,
        "image_model": image_model,
        "prompt_writer": gemini_model or "fallback-template",
        "reason": reason,
        "prompt": prompt_text,
        "resolution": f"{width}x{height}",
        "appearance": char.get("appearance") or {},
        "prev_version": (prev or {}).get("version"),
    }


# ---------- 버전 생성 ----------


def ensure_char_dir(cid):
    d = IMAGE_DIR / cid
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_prompt_files(cdir, base, meta, prompt_text):
    cdir.joinpath(base + ".prompt.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    cdir.joinpath(base + ".prompt.txt").write_text(prompt_text.rstrip() + "\n", encoding="utf-8", newline="\n")


def choose_size(char):
    # 턴어라운드(3뷰)는 넓은 화면 비율이 유리. 모델마다 제한이 있을 수 있으므로
    # 기본 1280x768, 실패하면 정사각형(1024x1024 / 896x896)으로 낮춰 재시도한다.
    return 1280, 768


def make_version(char, world, reason, width=None, height=None, image_size_fallback=None):
    """캐릭터 외관 이미지 한 버전을 생성·저장하고 characters.json에 버전 기록한다.

    reason: 버전 사유 (신규/외관 변경).
    리턴: 저장된 버전 dict; 실패 시 None.
    """
    cid = char["id"]
    cdir = ensure_char_dir(cid)
    imgs = list(char.get("appearance_images") or [])
    version = (imgs[-1]["version"] + 1) if imgs else 1
    base = f"appearance_v{version}"

    if not width or not height:
        width, height = choose_size(char)
    sizes = [(width, height)]
    if image_size_fallback:
        sizes = sizes + [tuple(x) for x in image_size_fallback]

    data = None
    prompt_text = None
    image_model = None
    gemini_model = None
    last_err = None
    for w, h in sizes:
        try:
            data, prompt_text, image_model, gemini_model = pollinations_image(char, world, w, h)
            break
        except ApiError as e:
            last_err = str(e)
            log(f"    {w}x{h} 실패: {e}")
    if data is None:
        log(f"  [{cid}] 이미지 생성 실패: {last_err}")
        return None

    ext = guess_ext(data)
    img_name = base + "." + ext
    cdir.joinpath(img_name).write_bytes(data)
    pj_name = base + ".prompt.json"
    pt_name = base + ".prompt.txt"

    meta = build_prompt_meta(
        char, version, prompt_text, gemini_model, image_model, w, h, reason, imgs[-1] if imgs else None,
    )
    meta["image_file"] = img_name
    save_prompt_files(cdir, base, meta, prompt_text or fallback_prompt(char, world))

    rec = {
        "version": version,
        "created_at": now_iso(),
        "reason": reason,
        "file": img_name,
        "prompt_json": pj_name,
        "prompt_txt": pt_name,
        "appearance_hash": current_hash(char),
        "appearance": char.get("appearance") or {},
        "image_model": image_model,
    }
    imgs.append(rec)
    char["appearance_images"] = imgs
    log(f"  [{cid}] v{version} 생성 완료: {img_name} → content/images/characters/{cid}/")
    log(f"      프롬프트 저장: {pj_name} / {pt_name}")
    return rec


def run(characters=None, world=None, force=False, only=None, width=None, height=None, image_size_fallback=None):
    """전체 캐릭터의 이미지 생성 여부를 확인하고 필요한 버전을 생성한다.

    - only: 특정 캐릭터 id만 처리 (없으면 전체)
    - force: True이면 외관이 바뀌지 않아도 재생성
    리턴: 생성된 버전 목록.
    """
    if characters is None:
        characters = load_json("characters.json")
    if world is None:
        world = load_json("world.json")

    key = get_pollin_key()
    if not key:
        log("POLLIN_API_KEY가 없어 이미지 생성을 건너뜁니다. (로컬 .env 또는 GitHub Secrets)")
        return []

    made = []
    for char in characters:
        cid = char.get("id")
        if only and cid not in only:
            continue
        app = char.get("appearance") or {}
        if not app:
            continue
        if not force and not needs_image(char):
            latest = latest_version(char)
            log(f"  [{cid}] 외관 변화 없음 (v{latest['version']} 유지)")
            continue
        reason = "신규 캐릭터" if not latest_version(char) else "외관 변경"
        log(f"[{cid}] 이미지 생성 필요 ({reason}) — Pollinations 호출…")
        rec = make_version(char, world, reason, width=width, height=height, image_size_fallback=image_size_fallback)
        if rec:
            made.append((cid, rec))

    if made:
        save_json("characters.json", characters)
        log(f"이미지 생성 완료: {len(made)}건")
    return made


def main():
    load_env()
    args = sys.argv[1:]
    force = "--force" in args
    only = None
    width = height = None
    for i, a in enumerate(args):
        if a == "--only" and i + 1 < len(args):
            only = [x.strip() for x in args[i + 1].split(",") if x.strip()]
        if a == "--size" and i + 1 < len(args):
            try:
                width, height = [int(x) for x in args[i + 1].split("x")]
            except ValueError:
                pass
    run(force=force, only=only, width=width, height=height)


if __name__ == "__main__":
    main()