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


def build_gen_prompt(char, world, prev_appearance):
    w = world
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


def make_prompt_with_gemini(char, world, prev_appearance):
    key = get_gemini_key()
    models = get_gemini_models()
    if not key:
        return None, None
    prompt = build_gen_prompt(char, world, prev_appearance)
    errors = []
    for m in models:
        try:
            data = call_gemini_text(m, key, prompt)
            raw = (data or {}).get("prompt") or ""
            p = re.sub(r"\s+", " ", raw).strip()
            if len(p) > 30:
                log(f"    프롬프트 작성 모델: {m}")
                return p, m
            errors.append(f"{m}: 프롬프트가 너무 짧음")
        except ApiError as e:
            if not e.rotate:
                log(f"    프롬프트 작성 실패({m}): {e} → 템플릿 사용")
                return None, None
            errors.append(str(e))
            log(f"    프롬프트 모델 {m} 사용 불가 → 다음 모델")
    log("    Gemini 프롬프트 작성 실패 (" + "; ".join(errors) + ") → 템플릿 사용")
    return None, None


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


def guess_ext(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpg"
    return "bin"


def pollinations_image(char, world, width, height):
    """외관 기준 이미지 1장을 생성한다. (리턴=바이트, 프롬프트, 이미지 모델, 프롬프트 작성 모델)"""
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
    prompt_text, gemini_model = make_prompt_with_gemini(char, world, prev_appearance)
    if prompt_text is None:
        prompt_text = fallback_prompt(char, world)

    if not width or not height:
        width, height = 1024, 1024
    models = get_image_models()
    errors = []
    for m in models:
        try:
            data = call_pollinations(prompt_text, m, width, height)
            if len(data) < 1000:
                raise ApiError(f"{m} 응답이 너무 작음({len(data)} bytes)")
            log(f"    이미지 생성 모델: {m} · {len(data)} bytes · size={width}x{height}")
            return data, prompt_text, m, gemini_model
        except ApiError as e:
            errors.append(str(e))
            log(f"    이미지 모델 {m} 실패: {e}" + (" → 다음 모델" if e.rotate else ""))
    raise ApiError("이미지 모델 모두 실패: " + " | ".join(errors))


def build_prompt_meta(char, version, prompt_text, gemini_model, image_model, width, height, reason, prev):
    return {
        "version": version,
        "created_at": now_iso(),
        "generator": "pollinations-gen",
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