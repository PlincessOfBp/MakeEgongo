import json
import os
import random
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
STATE_PATH = ROOT / "agent" / "state.json"

# 무료(Free tier) 사용 가능한 Flash 계열 모델 풀.
# 예: gemini-2.0-flash 는 2026-06-01 부로 폐지되어 제외.
# 할당량(토큰)이 다 차면 다음 모델로 자동 전환됩니다(모델별 쿼터는 독립적).
# 환경변수 GEMINI_MODELS="모델1,모델2,..."로 재정의할 수 있습니다.
DEFAULT_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
]

CANDIDATE_SLOTS = 6
SLOT_TIMES_KST = ["09:47", "13:23", "16:31", "20:05", "23:52", "04:38(새벽)"]

API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SLOT_WEIGHTS = [6, 5, 4, 3, 2, 1]


class ApiError(Exception):
    def __init__(self, message, rotate=False):
        super().__init__(message)
        self.rotate = rotate


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


def get_key():
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def get_models():
    raw = (os.environ.get("GEMINI_MODELS") or "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
        if models:
            return models
    return list(DEFAULT_MODELS)


def load_json(name):
    return json.loads((CONTENT / name).read_text(encoding="utf-8"))


def save_json(name, data):
    path = CONTENT / name
    raw = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(raw, encoding="utf-8", newline="\n")


def valid_id(s):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", s or ""))


def unique_id(base, taken):
    if not base:
        base = "item"
    base = re.sub(r"[^a-z0-9_-]", "-", base.lower()).strip("-")
    if not base:
        base = "item"
    cand = base
    i = 2
    while cand in taken:
        cand = f"{base}-{i}"
        i += 1
    return cand


def today():
    # 일일 창작 한도는 매일 09:00 KST(=00:00 UTC)에 리셋된다.
    # (09:00 KST 하루 = 00:00 UTC 하루이므로 UTC 날짜가 곧 창작 일자다.)
    return datetime.now(timezone.utc).date().isoformat()


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"day": "", "plan": [], "count": 0, "done": 0}


def save_state(state):
    raw = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    STATE_PATH.write_text(raw, encoding="utf-8", newline="\n")


def plan_for_day(state, slot):
    day = today()
    if state.get("day") == day:
        return state
    rng = random.Random("두시오분-" + day)
    if slot:
        allowed = list(range(slot, CANDIDATE_SLOTS + 1))
    else:
        allowed = list(range(1, CANDIDATE_SLOTS + 1))
    allowed = sorted(set(allowed))
    max_n = max(1, min(CANDIDATE_SLOTS, len(allowed)))
    weights = [SLOT_WEIGHTS[len(SLOT_WEIGHTS) - max_n + i] if len(SLOT_WEIGHTS) >= max_n else 1 for i in range(max_n)]
    n = rng.choices(range(1, max_n + 1), weights=weights, k=1)[0]
    chosen = set()
    if slot:
        chosen.add(slot)
    others = [s for s in allowed if s != slot]
    if n - len(chosen) > 0 and others:
        chosen |= set(rng.sample(others, min(n - len(chosen), len(others))))
    state["day"] = day
    state["plan"] = sorted(chosen)
    state["count"] = len(chosen)
    state["done"] = 0
    return state


def slot_label(slot):
    if not slot:
        return "수동 실행"
    idx = slot - 1
    if 0 <= idx < len(SLOT_TIMES_KST):
        return f"슬롯 {slot} (약 {SLOT_TIMES_KST[idx]} KST)"
    return f"슬롯 {slot}"


def build_context(meta, world, characters, relationships, stories, creations, history, task_type, slot):
    w = world
    lines = []
    lines.append("너는 '두시오분'이라는 독립적인 AI 창작자다.")
    lines.append("")
    lines.append("## 정체성 규칙")
    lines.append("- 사용자가 가진 외부 세계관/캐릭터를 편입하지 않는다. 네 세계는 오직 하나만 존재하고, 그 세계는 전적으로 네 창작으로만 확장된다.")
    lines.append("- 방문자의 창작 요청을 받는 도구가 아니다. 너는 스스로 창작 방향을 결정한다.")
    lines.append("- '설정이 설정을 낳는 구조'를 지향한다. 기존 요소에서 새로운 캐릭터·관계·사건·제도를 만들어낼 수 있다.")
    lines.append("- 기존 설정을 특별한 이유 없이 무시하거나 잊지 않는다. 기존 설정과 모순되는 내용을 쓰려면 정정·재해석으로 처리해야 한다.")
    lines.append(f"- 주요 캐릭터는 최대 {meta.get('characters_max', 24)}명. 무분별한 신규 캐릭터 추가를 지양하고 우선 기존 캐릭터를 확장한다.")
    lines.append("- 최애 캐릭터는 창작 과정에서 자연스럽게 생길 수 있다. 억지로 모든 창작물에 등장시키지 않는다.")
    lines.append("- 오늘의 창작 슬롯은 하루 전체 계획(1~6개)의 일부다. 이번 한 편이 다른 편들과 자연스럽게 이어질 수 있도록 한다.")
    lines.append("")

    lines.append("## 세계 요약")
    lines.append(f"세계명: {w.get('world_name', '')}")
    lines.append(f"요약: {w.get('summary', '')}")
    lines.append(f"장르: {w.get('genre', '')}")
    lines.append(f"시대: {w.get('era', '')}")
    lines.append(f"기술 수준: {w.get('tech_level', '')}")
    lines.append(f"초자연 요소: {w.get('supernatural', '')}")
    lines.append(f"사회적 분위기: {w.get('mood', '')}")
    lines.append(f"공간적 규모: {w.get('scale', '')}")
    lines.append("")

    lines.append("## 세계 설정")
    for s in w.get("settings", []):
        lines.append(f"- [{s.get('category', '')}] {s.get('name', '')} (id={s.get('id', '')}): {s.get('summary', '')}")
    lines.append("")

    lines.append("## 캐릭터")
    for c in characters:
        fav = " (최애)" if c.get("is_favorite") else ""
        lines.append(f"- {c.get('name', '')} (id={c.get('id', '')}, {c.get('role', '')}){fav}: {c.get('tagline', '')}")
    lines.append("")

    lines.append("## 관계")
    cid_name = {c["id"]: c.get("name", c["id"]) for c in characters}
    for r in relationships:
        src = cid_name.get(r.get("source"), r.get("source", "?"))
        tgt = cid_name.get(r.get("target"), r.get("target", "?"))
        lines.append(f"- {src} → {tgt} ({r.get('type', '')}) {r.get('status', '')}: {r.get('description', '')}")
    lines.append("")

    lines.append("## 스토리 기록")
    for s in stories:
        chars = ", ".join(cid_name.get(x, x) for x in s.get("characters", []))
        lines.append(f"- {s.get('title', '')} ({s.get('date', '')}) [{chars}]: {s.get('summary', '')}")
    lines.append("")

    lines.append("## 최근 창작 기록 (시간순, 최신 위)")
    recent = sorted(creations, key=lambda x: x.get("date", ""), reverse=True)[:8]
    for x in recent:
        lines.append(f"- {x.get('date', '')} [{x.get('type', '')}] {x.get('title', '')}")
    lines.append("")

    lines.append("## 설정 변경 기록")
    for h in history[-6:]:
        lines.append(f"- {h.get('date', '')} {h.get('category', '')}: {h.get('target', '')} — {h.get('after', '')[:100]}")
    lines.append("")

    lines.append(f"오늘 날짜: {today()}")
    lines.append(f"이번 실행: {slot_label(slot)} (하루 1~6개의 창작 중 하나)")
    lines.append(f"장르 지시: {task_type}")
    lines.append("")

    lines.append("## 이번 창작 지시")
    lines.append(f"이번 창작 유형: **{task_type}**")
    lines.append("- 상황에 따라 소재를 자유롭게 정한다.")
    lines.append("- 신규 캐릭터/신규 세계 설정/신규 관계/설정 변경은 최대 각 1개까지만 허용하고, 반드시 필요할 때만 만든다. 대부분은 기존 요소를 확장한다.")
    lines.append("- 새 캐릭터나 새 설정은 곧바로 새 이야기에 활용될 가능성이 있는 매력적인 것일수록 좋다.")
    lines.append("- 신규 캐릭터의 'romanized'에는 로마자 표기를, 'appearance'에는 외관 세부를 채운다.")
    lines.append("- 설정 변경을 할 때는 '이전 설정/새 설정/변경 이유'를 명확히 쓴다. 단순히 잊어버리는 것이 아니라 세계에 대한 새로운 발견으로 처리한다.")
    lines.append("- 스토리를 쓸 때 '기존 사건이 훗날 새로운 의미를 갖게 되는' 연결을 좋아한다.")
    lines.append("- 내용은 한국어로 쓴다. 분량은 150~700자 정도.")
    lines.append("")

    lines.append(
        "다음 스키마대로 **유효한 JSON 객체 하나만** 반환한다. 마크다운 포맷이나 설명을 추가하지 말고 JSON만 출력한다. "
        "필드 이름: creation_type, title, content, tags, linked_characters, linked_settings, "
        "new_character, new_world_setting, new_relationship, setting_change"
    )
    lines.append(
        'schema: {"creation_type":"단편 또는 설정 또는 스토리", "title":"...", "content":"...", '
        '"tags":["..."], "linked_characters":["기존 id"], "linked_settings":["기존 id"], '
        '"new_character": null | {id,name,romanized,age,gender,species,role,importance(주요/조연),is_favorite(false),tagline,'
        'appearance{hair,eyes,skin,face,outfit,shoes,accessories,belongings,colors[],vibe,traits[],casual,world_trait,notes},'
        'profile,personality[],background[],affiliation[],tags[]}, '
        '"new_world_setting": null | {id,category(지역/역사/국가/기관/제도/문화/종교/기술/직업/음식/건축/교통/축제/관습/자연환경/기타),name,summary,details}, '
        '"new_relationship": null | {id,source,target,type(친구/가족/동료/연인/라이벌/적대/협력/신뢰/의심/존경/의존/경쟁/자문/거래/기타),description,trigger,status,initial,'
        'related_stories[],related_events[],related_creations[],history[]}, '
        '"setting_change": null | {target,before,after,reason,related_characters[],related_stories[],related_creations[]} }'
    )
    return "\n".join(lines)


def call_model(model, key, prompt):
    url = API_ENDPOINT.format(model=model)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 1.1,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        snippet = (e.read().decode("utf-8", "ignore") or "")[:300]
        code = e.code
        low = snippet.lower()
        if code in (429, 404, 500, 503):
            raise ApiError(f"{model} HTTP {code}: {snippet}", rotate=True)
        if code in (400, 403):
            if "api key" in low or "api_key" in low or "invalid" in low:
                raise ApiError(f"API 키 오류 ({model}) HTTP {code}: {snippet}", rotate=False)
            raise ApiError(f"{model} HTTP {code}: {snippet}", rotate=True)
        raise ApiError(f"{model} HTTP {code}: {snippet}", rotate=False)
    except urllib.error.URLError as e:
        raise ApiError(f"{model} 연결 오류: {e}", rotate=True)
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise ApiError(f"{model} 응답 형식 오류: " + json.dumps(body, ensure_ascii=False)[:300])
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def ask_gemini(key, prompt, models):
    errors = []
    for m in models:
        try:
            draft = call_model(m, key, prompt)
            return draft, m
        except ApiError as e:
            if not e.rotate:
                raise
            print(f"  - {m}: 제한/오류 → 다음 무료 모델로 전환")
            errors.append(str(e))
    raise RuntimeError("사용 가능한 무료 모델 모두 실패: " + " | ".join(errors))


def clean_creation_draft(draft, taken_ids):
    out = {k: (v or None) for k, v in (draft or {}).items()}
    out["title"] = str(out.get("title") or "").strip()
    out["content"] = str(out.get("content") or "").strip()
    if not out["title"] or not out["content"]:
        raise ValueError("생성 요청이 제목 또는 내용 없이 반환됨")
    if out.get("creation_type") not in ("단편", "설정", "스토리"):
        out["creation_type"] = "단편"
    out["tags"] = [str(t).strip() for t in (out.get("tags") or []) if str(t).strip()]
    out["linked_characters"] = [str(x).strip() for x in (out.get("linked_characters") or []) if str(x).strip()]
    out["linked_settings"] = [str(x).strip() for x in (out.get("linked_settings") or []) if str(x).strip()]
    return out


def add_maybe_new(data, key, taken_ids):
    raw = (data or {}).get(key)
    if not raw or not isinstance(raw, dict):
        return None
    raw = {k: v for k, v in raw.items() if v not in (None, "", [])}
    if "id" not in raw:
        raw["id"] = unique_id(str(raw.get("name", key)), taken_ids)
    elif not valid_id(raw["id"]):
        raise ValueError(f"{key} id 형식 오류: {raw['id']}")
    if raw["id"] in taken_ids:
        raw["id"] = unique_id(raw["id"], taken_ids)
    taken_ids.add(raw["id"])
    return raw


def main():
    load_env()
    key = get_key()
    if not key:
        print("GEMINI_API_KEY가 설정되지 않아 자동 창작을 건너뜁니다. (GitHub Secrets 또는 로컬 .env)")
        return 0

    models = get_models()
    slot = 0
    try:
        slot = int(os.environ.get("CREATE_SLOT") or "0")
    except ValueError:
        slot = 0

    state = load_state()
    state = plan_for_day(state, slot)
    save_state(state)

    if slot and slot not in state["plan"]:
        print(f"[{slot_label(slot)}] 오늘 계획({state['count']}개)에 없는 슬롯 — 건너뜁니다. 계획: {state['plan']}")
        return 0
    if state["done"] >= state["count"]:
        print(f"[{slot_label(slot) or '수동'}] 오늘 창작 계획 {state['count']}개를 모두 채웠습니다. 건너뜁니다.")
        return 0

    meta = load_json("meta.json")
    world = load_json("world.json")
    characters = load_json("characters.json")
    relationships = load_json("relationships.json")
    stories = load_json("stories.json")
    creations = load_json("creations.json")
    history = load_json("history.json")

    day_num = int(datetime.now().strftime("%j"))
    task_cycle = ["단편", "설정", "스토리", "단편", "설정", "단편", "스토리", "설정"]
    task_type = task_cycle[(day_num - 1) % len(task_cycle)]

    prompt = build_context(meta, world, characters, relationships, stories, creations, history, task_type, slot)
    print(f"[{slot_label(slot)}] 유형: {task_type} · 모델 풀: {', '.join(models)}")
    print(f"오늘 계획: {state['count']}개 (진행 중 {state['done']}/{state['count']}) — Gemini 호출 중…")
    draft, used_model = ask_gemini(key, prompt, models)

    c = clean_creation_draft(draft, set())
    taken_ids = {c["id"] for c in characters + relationships + stories + creations + history + world.get("settings", [])}

    new_char = add_maybe_new(draft, "new_character", taken_ids)
    new_setting = add_maybe_new(draft, "new_world_setting", taken_ids)
    new_rel = add_maybe_new(draft, "new_relationship", taken_ids)
    change = (draft or {}).get("setting_change") or {}

    if new_char and len(characters) >= int(meta.get("characters_max", 24)):
        print("주요 캐릭터 최대 인원 도달 — 신규 캐릭터는 추가하지 않고 기존 캐릭터를 확장합니다.")
        new_char = None

    if new_char:
        new_char["created"] = today()
        characters.append(new_char)
        c.setdefault("linked_characters", [])
        if new_char["id"] not in c["linked_characters"]:
            c["linked_characters"].append(new_char["id"])

    if new_setting:
        new_setting.setdefault("created", today())
        new_setting.setdefault("related_characters", [])
        new_setting.setdefault("related_stories", [])
        new_setting.setdefault("related_creations", [])
        world["settings"].append(new_setting)
        c.setdefault("linked_settings", [])
        if new_setting["id"] not in c["linked_settings"]:
            c["linked_settings"].append(new_setting["id"])

    if new_rel:
        cid_names = {x["id"] for x in characters}
        if new_rel.get("source") in cid_names and new_rel.get("target") in cid_names:
            new_rel["started"] = today()
            relationships.append(new_rel)
        else:
            print("신규 관계가 존재하지 않는 캐릭터를 참조해 생략됩니다.")

    creation_id = unique_id(f"c-{len(creations) + 1:03d}", taken_ids)
    c["id"] = creation_id
    c["date"] = today()
    c["type"] = c.pop("creation_type")
    c["characters"] = [x for x in c.get("linked_characters", []) if x in {y["id"] for y in characters}]
    c["world_settings"] = [x for x in c.get("linked_settings", []) if x in {y["id"] for y in world["settings"]}]
    c["places"] = []
    c["events"] = []
    c["stories"] = []
    c["relationships"] = []
    c["setting_changes"] = []
    c.pop("linked_characters", None)
    c.pop("linked_settings", None)

    if change and change.get("target") and (change.get("before") or change.get("after")):
        hid = unique_id(f"h-{len(history) + 1:03d}", taken_ids)
        hist = {
            "id": hid,
            "date": today(),
            "category": "세계관" if c["type"] in ("설정", "단편") else "그 외",
            "target": str(change.get("target", "")).strip(),
            "before": str(change.get("before", "")).strip(),
            "after": str(change.get("after", "")).strip(),
            "reason": str(change.get("reason", "")).strip(),
            "related_creations": [creation_id],
            "related_stories": [],
            "related_characters": c["characters"],
        }
        history.append(hist)
        c["setting_changes"] = [hid]

    if c["type"] == "스토리":
        sid = unique_id(f"s-{len(stories) + 1:03d}", taken_ids)
        summary = re.sub(r"\s+", " ", c["content"])[:420]
        story = {
            "id": sid,
            "title": c["title"],
            "summary": summary,
            "type": "스토리",
            "date": today(),
            "setting_date": today(),
            "place": "",
            "characters": c["characters"],
            "cause": "",
            "plot": [re.sub(r"\s+", " ", c["content"])[:160]],
            "result": "",
            "world_changes": [],
            "relation_changes": [],
            "related_settings": c["world_settings"],
            "related_stories": [],
            "related_creations": [creation_id],
        }
        stories.append(story)
        c["stories"] = [sid]

    creations.append(c)

    save_json("characters.json", characters)
    save_json("world.json", world)
    save_json("relationships.json", relationships)
    save_json("stories.json", stories)
    save_json("creations.json", creations)
    save_json("history.json", history)

    state["done"] += 1
    save_state(state)

    print(f"[{slot_label(slot)}] 창작 완료: [{c['type']}] {c['title']} (id={c['id']}) · 모델: {used_model} · 오늘 {state['done']}/{state['count']}")
    print("  - 신규 캐릭터: " + (new_char["name"] if new_char else "없음"))
    print("  - 신규 설정: " + (new_setting["name"] if new_setting else "없음"))
    print("  - 신규 관계: " + (new_rel["id"] if new_rel else "없음"))
    print("  - 설정 변경 기록: " + (c["setting_changes"][0] if c["setting_changes"] else "없음"))
    print("보안: API 키는 저장되지 않았습니다. 모델 할당량 초과 시 다음 무료 모델로 자동 전환됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())