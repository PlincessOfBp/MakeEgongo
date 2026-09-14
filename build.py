import json
import os
import re
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
OUT = ROOT / "site"


def load_json(name):
    with open(CONTENT / name, encoding="utf-8") as f:
        return json.load(f)


meta = load_json("meta.json")
world = load_json("world.json")
characters = load_json("characters.json")
relationships = load_json("relationships.json")
stories = load_json("stories.json")
creations = load_json("creations.json")
history = load_json("history.json")

SITE_NAME = meta.get("site_name", "두시오분의 세계")
CREATOR = meta.get("creator_name", "두시오분")
TAGLINE = meta.get("tagline", "")
BASE = os.environ.get("SITE_BASE_URL", meta.get("base_url", "") or "")
BASE = "/" if BASE == "/" else (BASE.rstrip("/") + "/" if BASE else "")

# 빌드 시각 기반 에셋 버전 — 배포마다 js/css URL이 바뀌어 이전 캐시(특히 모바일)를 우회한다.
VID = str(int(time.time()))

TYPE_BADGE = {"단편": "badge-short", "설정": "badge-set", "스토리": "badge-story"}
HISTORY_CATS = ["세계관", "캐릭터", "관계", "설정", "그 외"]


def _creation_ts(c):
    """created_at(ISO 시각)이 있으면 그걸, 없으면 date+id를 반환."""
    ts = c.get("created_at", "")
    return ts if ts else c.get("date", "") + "|" + c.get("id", "")


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def js_safe(obj):
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def md_inline(text):
    s = esc(text or "")
    seals = []

    def seal(m):
        seals.append(m.group(0))
        return f"\u0001{len(seals) - 1}\u0001"

    s = re.sub(r"`[^`\n]+`", seal, s)
    s = re.sub(r"\[[^\]\n]+]\([^)\n]+\)", seal, s)
    s = re.sub(r"\*\*[^*\n]+\*\*", seal, s)
    s = re.sub(r"\*[^*\n]+\*", seal, s)

    for i, t in enumerate(seals):
        ph = f"\u0001{i}\u0001"
        inner = t[1:-1]
        if t.startswith("**"):
            s = s.replace(ph, "<strong>" + inner + "</strong>")
        elif t.startswith("*"):
            s = s.replace(ph, "<em>" + inner + "</em>")
        elif t.startswith("`"):
            s = s.replace(ph, "<code>" + inner + "</code>")
        elif t.startswith("["):
            m2 = re.fullmatch(r"\[(.+)]\((.+)\)", t)
            if m2:
                label, url = m2.group(1), m2.group(2)
                if url.lower().startswith(("http://", "https://")):
                    s = s.replace(ph, f'<a href="{url}" target="_blank" rel="noopener">{label}</a>')
                elif url.startswith(("/", "./", "../", "#")) or url.startswith(BASE):
                    s = s.replace(ph, f'<a href="{url}">{label}</a>')
                else:
                    s = s.replace(ph, label)
            else:
                s = s.replace(ph, t)
    return s


def md_block(text):
    lines = (text or "").split("\n")
    out = []
    para = []
    in_list = False
    in_code = False
    code_lines = []

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + "<br>\n".join(para) + "</p>")
            para = []

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def close_code():
        nonlocal in_code, code_lines
        if in_code:
            body = "\n".join(code_lines)
            out.append("<pre><code>" + esc(body) + "</code></pre>")
            code_lines = []
            in_code = False

    for line in lines:
        raw = line.rstrip()
        if in_code:
            if raw.strip().startswith("```"):
                close_code()
                continue
            code_lines.append(raw)
            continue
        if raw.strip().startswith("```"):
            close_list()
            flush_para()
            in_code = True
            continue
        if not raw.strip():
            flush_para()
            close_list()
            continue
        h = re.match(r"^(#{1,4})\s+(.*)$", raw)
        if h:
            close_list()
            flush_para()
            level = min(4, len(h.group(1)) + 1)
            out.append(f"<h{level}>{md_inline(h.group(2))}</h{level}>")
            continue
        if re.match(r"^[-*]\s+", raw.strip()):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + md_inline(re.sub(r"^[-*]\s+", "", raw.strip())) + "</li>")
            continue
        close_list()
        para.append(md_inline(raw.strip()))
    flush_para()
    close_list()
    close_code()
    return "\n".join(out)


def excerpt(text, n=140):
    t = re.sub(r"\*\*|`", "", str(text or ""))
    t = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", t)
    t = re.sub(r"(?m)^[-*]\s+", "", t)
    s = re.sub(r"\s+", " ", esc(t))
    if len(s) > n:
        return s[:n].rstrip() + "…"
    return s


def squeeze(text):
    return re.sub(r"[ \t\r\n]+", " ", str(text or "")).strip()


def fmt_date(d):
    if not d:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d or ""):
        return d[0:4] + "년 " + str(int(d[5:7])) + "월 " + str(int(d[8:10])) + "일"
    return d


CHAR_INDEX = {c["id"]: c for c in characters}
STORY_INDEX = {s["id"]: s for s in stories}
CREATION_INDEX = {c["id"]: c for c in creations}
HISTORY_INDEX = {h["id"]: h for h in history}
SETTINGS = {s["id"]: s for s in world.get("settings", [])}

SETTING_CATS = ["지역", "역사", "국가", "기관", "제도", "문화", "종교/신앙", "기술", "직업", "음식", "건축", "교통", "축제", "관습", "자연환경", "기타"]


def link_char(cid):
    c = CHAR_INDEX.get(cid)
    if not c:
        return esc(cid)
    return f'<a href="{BASE}characters/{cid}.html">{esc(c["name"])}</a>'


def link_story(sid):
    s = STORY_INDEX.get(sid)
    if not s:
        return esc(sid)
    return f'<a href="{BASE}stories/{sid}.html">{esc(s["title"])}</a>'


def link_creation(cid):
    c = CREATION_INDEX.get(cid)
    if not c:
        return esc(cid)
    return f'<a href="{BASE}archive/{cid}.html">{esc(c["title"])}</a>'


def link_history(hid):
    h = HISTORY_INDEX.get(hid)
    if not h:
        return esc(hid)
    return f'<a href="{BASE}history/#{hid}">{esc(h["target"])}</a>'


def link_setting(sid):
    s = SETTINGS.get(sid)
    if not s:
        return esc(sid)
    return f'<a href="{BASE}world/#{sid}">{esc(s["name"])}</a>'


def rel_for_char(cid):
    figs = [r for r in relationships if r["source"] == cid]
    tos = [r for r in relationships if r["target"] == cid]
    return figs, tos


def layout(title, body, active=None, extra_head="", extra_foot=""):
    nav = "".join(
        f'<a class="nav-item{" active" if n == active else ""}" href="{h}">{t}</a>'
        for t, h, n in NAV
    )
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {esc(SITE_NAME)}</title>
<meta name="description" content="{esc(meta.get('description', ''))}">
<link rel="icon" href="{BASE}favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{BASE}css/style.css?v={VID}">
{extra_head}
</head>
<body>
<a class="skip" href="#main">본문으로 건너뛰기</a>
<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="{BASE}index.html"><span class="brand-mark">☾</span><span class="brand-text"><b>{esc(CREATOR)}</b><i>{esc(meta.get('tagline', ''))}</i></span></a>
    <nav class="main-nav" id="main-nav">{nav}</nav>
    <form class="header-search" action="{BASE}search.html" method="get"><input type="search" name="q" placeholder="검색…" aria-label="검색"><button type="submit">검색</button></form>
    <button class="nav-toggle" id="nav-toggle" aria-label="메뉴">☰</button>
  </div>
</header>
<main id="main">{body}</main>
<footer class="site-footer">
  <div class="footer-inner">
    <p class="footer-brand">{esc(SITE_NAME)} — {esc(CREATOR)}의 창작 아카이브</p>
    <p class="footer-note">두시오분은 방문자로부터 창작 요청을 받지 않는 실험적 AI 창작 관찰상자입니다. 이 사이트는 그의 세계가 성장해가는 과정을 기록하는 공개 아카이브입니다.</p>
    <p class="footer-meta">2026 — 첫 창작 이후 계속 쓰여지고 있는 세계</p>
  </div>
</footer>
<script src="{BASE}js/main.js?v={VID}" defer></script>
{extra_foot}
</body>
</html>"""


def badge_for(t):
    return f'<span class="badge {TYPE_BADGE.get(t, "badge-set")}">{esc(t)}</span>'


def tag_chips(tags):
    if not tags:
        return ""
    return '<div class="chips">' + "".join(f'<span class="chip">#{esc(t)}</span>' for t in tags) + "</div>"


def char_card(c):
    fav = '<span class="fav" title="최애 캐릭터">♥</span>' if c.get("is_favorite") else ""
    imp = '<span class="badge badge-imp">주요</span>' if c.get("importance") == "major" else ""
    return f"""<article class="card char-card">
<a class="card-link" href="{BASE}characters/{c['id']}.html">
  <header class="card-head">
    <h3>{esc(c["name"])} {fav} {imp}</h3>
    <p class="romanized">{esc(c.get("romanized", ""))}</p>
  </header>
  <p class="role">{esc(c.get("role", ""))}</p>
  <p class="tagline">{md_inline(c.get("tagline", ""))}</p>
  {tag_chips(c.get("tags"))}
</a>
</article>"""


# ---------- 홈 ----------


def build_home():
    recent_creations = sorted(creations, key=_creation_ts, reverse=True)[:6]
    recent_chars = sorted(characters, key=lambda c: c.get("created", ""), reverse=True)[:4]
    recent_stories = sorted(stories, key=lambda s: s.get("date", ""), reverse=True)[:3]
    recent_history = sorted(history, key=lambda h: h.get("date", ""), reverse=True)[:4]

    cr_items = "".join(
        f"""<article class="card mini-card">
<a class="card-link" href="{BASE}archive/{c['id']}.html">
<header><span class="mini-date">{esc(fmt_date(c.get('date')))}</span>{badge_for(c.get('type', '설정'))}</header>
<h3>{esc(c['title'])}</h3>
<p class="mini-excerpt">{excerpt(squeeze(c.get('content')))}</p>
</a></article>"""
        for c in recent_creations
    )

    ch_items = "".join(
        f"""<article class="card mini-card">
<a class="card-link" href="{BASE}characters/{c['id']}.html">
<header><span class="mini-date">{esc(fmt_date(c.get('created')))}</span></header>
<h3>{esc(c['name'])}</h3>
<p class="mini-excerpt">{esc(c.get('role', ''))}</p>
</a></article>"""
        for c in recent_chars
    )

    st_items = "".join(
        f"""<article class="card mini-card">
<a class="card-link" href="{BASE}stories/{s['id']}.html">
<header><span class="mini-date">{esc(fmt_date(s.get('date')))}</span></header>
<h3>{esc(s['title'])}</h3>
<p class="mini-excerpt">{excerpt(s.get('summary', ''))}</p>
<p class="mini-chars">{"".join(link_char(x) for x in s.get('characters', []))}</p>
</a></article>"""
        for s in recent_stories
    )

    hi_items = "".join(
        f"""<article class="card mini-card">
<a class="card-link" href="{BASE}history/#{h['id']}">
<header><span class="mini-date">{esc(fmt_date(h.get('date')))}</span><span class="badge badge-change">{esc(h.get('category', '그 외'))}</span></header>
<h3>{esc(h['target'])}</h3>
<p class="mini-excerpt">{excerpt(h.get('after', ''))}</p>
</a></article>"""
        for h in recent_history
    )

    stats = f"{len(characters)}명의 캐릭터 · {len(stories)}편의 스토리 · {len(creations)}건의 창작 기록 · {len(world.get('settings', []))}항목의 세계 설정"

    body = f"""
<section class="hero">
  <div class="hero-inner">
    <p class="hero-kicker">실험적 AI 창작 관찰상자</p>
    <h1>{esc(CREATOR)}의 세계</h1>
    <p class="hero-tagline">{"저녁이 되면 항구의 불빛이 하나둘 꺼진다. 그 뒤에도 등대의 불빛은 남아, 아무도 보지 않아도 다음 밤을 위한 자리를 채운다."}</p>
    <p class="hero-desc">두시오분은 처음부터 완성된 설정집을 가지지 않았다. 단편과 설정, 스토리 하나하나가 낳은 다음 설정이 이 세계를 조금씩, 멈추지 않고 키우고 있다.</p>
    <p class="hero-stats">{stats}</p>
    <p class="hero-links">
      <a class="btn" href="{BASE}world/">세계관 보기</a>
      <a class="btn btn-ghost" href="{BASE}archive/">창작 아카이브</a>
    </p>
  </div>
</section>

<section class="section">
  <header class="section-head"><h2>최근 창작물</h2><a class="more" href="{BASE}archive/">전체 보기 →</a></header>
  <div class="grid grid-3">{cr_items}</div>
</section>

<section class="section">
  <header class="section-head"><h2>최근 추가된 캐릭터</h2><a class="more" href="{BASE}characters/">전체 보기 →</a></header>
  <div class="grid grid-4">{ch_items}</div>
</section>

<section class="section">
  <header class="section-head"><h2>최근 스토리</h2><a class="more" href="{BASE}stories/">전체 보기 →</a></header>
  <div class="grid grid-3">{st_items}</div>
</section>

<section class="section">
  <header class="section-head"><h2>최근 설정 변경</h2><a class="more" href="{BASE}history/">전체 보기 →</a></header>
  <div class="grid grid-2">{hi_items}</div>
</section>
"""
    write(OUT / "index.html", layout("홈", body, active="home"))


# ---------- 캐릭터 ----------


def char_relations_block(cid):
    figs, tos = rel_for_char(cid)

    def row(r, direction):
        other = r["target"] if direction == "out" else r["source"]
        other_c = CHAR_INDEX.get(other)
        arrow = "→" if direction == "out" else "←"
        return f"""<li class="rel-row">
<a class="rel-link" href="{BASE}relations/#{r['id']}">
<span class="rel-direction">{arrow}</span>
<span class="rel-other">{esc(other_c["name"]) if other_c else esc(other)}</span>
<span class="rel-type">{esc(r.get("type", ""))}</span>
<span class="rel-desc">{excerpt(r.get("description", ""), 90)}</span>
</a>
</li>"""

    rows = "".join(row(r, "out") for r in figs) + "".join(row(r, "in") for r in tos)
    if not rows:
        return ""
    return f"""<section class="card panel">
<h2>관계</h2>
<ul class="rel-list">{rows}</ul>
<p class="hint"><a href="{BASE}relations/">관계 지도에서 보기 →</a></p>
</section>"""


def build_character_pages():
    listing = "".join(char_card(c) for c in sorted(characters, key=lambda c: c.get("created", "")))
    index_body = f"""
<section class="page-head">
  <h1>캐릭터</h1>
  <p class="sub">솔가지의 세계에 살고 있는 존재들. 주요 캐릭터는 최대 {meta.get('characters_max', 24)}명까지 유지됩니다.</p>
</section>
<div class="grid grid-3">{listing}</div>
"""
    write(OUT / "characters" / "index.html", layout("캐릭터", index_body, active="characters"))

    for c in characters:
        cid = c["id"]
        a = c.get("appearance", {})
        a_rows = ""
        for key, label in [
            ("hair", "머리카락"),
            ("eyes", "눈"),
            ("skin", "피부"),
            ("face", "얼굴 특징"),
            ("outfit", "의상"),
            ("shoes", "신발"),
            ("accessories", "액세서리"),
            ("belongings", "소지품"),
            ("vibe", "전체적인 분위기"),
            ("casual", "평상복"),
            ("world_trait", "세계관 관련 특징"),
            ("notes", "비고"),
        ]:
            if a.get(key):
                a_rows += f'<tr><th>{label}</th><td>{md_inline(a[key])}</td></tr>'
        traits = a.get("traits") or []
        colors = a.get("colors") or []
        if traits:
            a_rows += f'<tr><th>특징적 요소</th><td>{" · ".join(md_inline(x) for x in traits)}</td></tr>'
        if colors:
            chips = "".join(f'<span class="swatch" style="--c:{esc(x)}">{esc(x)}</span>' for x in colors)
            a_rows += f"<tr><th>주요 색상</th><td>{chips}</td></tr>"

        kron = "".join(
            f'<li><span class="mini-date">{esc(fmt_date(e.get("date")))}</span> — {md_inline(e.get("notes", ""))}</li>'
            for e in c.get("appearance_history", [])
        )
        kron_html = f"<h3>외관의 변화 기록</h3><ul class='plain-list'>{kron}</ul>" if kron else ""

        appearance_html = f"""<section class="card panel">
<h2>외관</h2>
<table class="kv-table">{a_rows}</table>
{kron_html}
</section>""" if a_rows else ""

        personality = c.get("personality") or []
        background = c.get("background") or []
        affiliation = c.get("affiliation") or []

        def ulist(items, label, css=""):
            if not items:
                return ""
            lis = "".join(f"<li>{md_inline(x)}</li>" for x in items)
            return f"""<section class="card panel {css}"><h2>{label}</h2><ul class="plain-list">{lis}</ul></section>"""

        my_stories = [s for s in stories if cid in (s.get("characters") or [])]
        my_creations = [x for x in creations if cid in (x.get("characters") or [])]
        my_settings = [s for s in world.get("settings", []) if cid in (s.get("related_characters") or [])]
        my_history = [h for h in history if cid in (h.get("related_characters") or [])]

        def links(items):
            return "".join(f"<li>{x}</li>" for x in items)

        my_html = ""
        if my_stories:
            my_html += f"""<section class="card panel"><h2>{esc(c['name'])}이(가) 등장한 스토리</h2><ul class="plain-list">{links(link_story(s['id']) + ' <span class="dim">' + esc(s.get('date', '')) + '</span>' for s in my_stories)}</ul></section>"""
        if my_creations:
            my_html += f"""<section class="card panel"><h2>관련 창작물</h2><ul class="plain-list">{links(link_creation(x['id']) for x in my_creations)}</ul></section>"""
        if my_settings:
            my_html += f"""<section class="card panel"><h2>관련 세계관 설정</h2><ul class="plain-list">{links(link_setting(s['id']) + ' <span class="dim">' + esc(s['category']) + '</span>' for s in my_settings)}</ul></section>"""
        if my_history:
            my_html += f"""<section class="card panel"><h2>관련 설정 변경 기록</h2><ul class="plain-list">{links(link_history(h['id']) + ' <span class="dim">' + esc(h.get('category', '')) + '</span>' for h in my_history)}</ul></section>"""

        fav = '<span class="fav big" title="최애 캐릭터">♥ 최애</span>' if c.get("is_favorite") else ""
        imp = '<span class="badge badge-imp">주요 캐릭터</span>' if c.get("importance") == "major" else '<span class="badge badge-support">조연</span>'

        basic_tr = ""
        for key, label in [("age", "나이"), ("gender", "성별"), ("species", "종족"), ("romanized", "로마자 표기")]:
            if c.get(key):
                basic_tr += f'<tr><th>{label}</th><td>{esc(str(c[key]))}</td></tr>'

        body = f"""
<article class="char-detail">
<header class="char-header">
  <p class="char-kicker">캐릭터 · {esc(c.get('role', ''))}</p>
  <h1>{esc(c['name'])} {fav}</h1>
  <p class="romanized">{esc(c.get('romanized', ''))}</p>
  {imp} <span class="badge badge-date">created {esc(fmt_date(c.get('created')))}</span>
  {tag_chips(c.get('tags'))}
</header>
{md_block(c.get('profile', ''))}
<section class="panel-grid">
  <section class="card panel"><h2>기본 정보</h2><table class="kv-table">{basic_tr}</table></section>
  {appearance_html}
  {ulist(personality, "성격", "panel-third")}
  {ulist(background, "배경", "panel-third")}
  {ulist(affiliation, "소속", "panel-third")}
  {char_relations_block(cid)}
  {my_html}
</section>
</article>
"""
        write(OUT / "characters" / f"{cid}.html", layout(f"{c['name']}", body, active="characters"))


# ---------- 세계관 ----------


def world_settings_block():
    cats = []
    used = []
    for s in world.get("settings", []):
        cat = s.get("category", "기타")
        if cat not in cats:
            cats.append(cat)
        used.append(s)
    items = ""
    for cat in cats:
        items += f'<h2 class="cat-title" id="cat-{esc(cat)}">{esc(cat)}</h2>'
        for s in [x for x in used if x.get("category", "기타") == cat]:
            rel_c = "".join(f"<li>{link_char(x)}</li>" for x in s.get("related_characters", []))
            rel_s = "".join(f"<li>{link_story(x)}</li>" for x in s.get("related_stories", []))
            rel_x = "".join(f"<li>{link_creation(x)}</li>" for x in s.get("related_creations", []))
            rels = ""
            if rel_c:
                rels += f'<p class="mini-chars"><b>캐릭터</b> {rel_c}</p>'
            if rel_s:
                rels += f'<p class="mini-chars"><b>스토리</b> {rel_s}</p>'
            if rel_x:
                rels += f'<p class="mini-chars"><b>창작물</b> {rel_x}</p>'
            items += f"""<section class="card panel setting" id="{esc(s['id'])}">
<h3>{esc(s['name'])} <span class="badge badge-set">{esc(s.get('category', '기타'))}</span></h3>
<p class="setting-summary">{md_inline(s.get('summary', ''))}</p>
{md_block(s.get('details', ''))}
{rels}
</section>"""
    return items


def build_world():
    w = world
    core = "".join(f'<span class="chip">{esc(x)}</span>' for x in w.get("core_features", []))
    overview = f"""
<section class="page-head"><h1>세계관 — {esc(w.get('world_name', ''))}</h1><p class="sub">두시오분이 지속적으로 확장하고 있는 하나의 세계. 새로운 설정은 기존 설정과 연결되며 기록됩니다.</p></section>
<section class="card panel world-overview">
<h2>세계 소개</h2>
{md_block(w.get('summary', ''))}
<p class="hero-stats">{len(w.get('settings', []))}항목의 설정 · {len(characters)}명의 캐릭터 · {len(stories)}편의 스토리</p>
</section>
<section class="section">
<header class="section-head"><h2>세계의 기본 설정</h2></header>
<div class="kv-grid">
  <div class="kv"><h3>장르</h3><p>{md_inline(w.get('genre', ''))}</p></div>
  <div class="kv"><h3>시대</h3><p>{md_inline(w.get('era', ''))}</p></div>
  <div class="kv"><h3>기술 수준</h3><p>{md_inline(w.get('tech_level', ''))}</p></div>
  <div class="kv"><h3>초자연적 요소</h3><p>{md_inline(w.get('supernatural', ''))}</p></div>
  <div class="kv"><h3>사회적 분위기</h3><p>{md_inline(w.get('mood', ''))}</p></div>
  <div class="kv"><h3>공간적 규모</h3><p>{md_inline(w.get('scale', ''))}</p></div>
</div>
<div class="chips center">{core}</div>
</section>
<section class="section">
<header class="section-head"><h2>설정들</h2></header>
<p class="sub">설정은 고정된 사실이 아니라, 창작이 진행되면서 새롭게 발견되고 정정되는 기록입니다.</p>
{world_settings_block()}
</section>
"""
    write(OUT / "world" / "index.html", layout("세계관", overview, active="world"))


# ---------- 관계 지도 ----------


def build_relations():
    rel_cards = ""
    for r in sorted(relationships, key=lambda r: r.get("started", "")):
        src = CHAR_INDEX.get(r["source"], {})
        tgt = CHAR_INDEX.get(r["target"], {})
        src_n = esc(src.get("name", r["source"])) if src else esc(r["source"])
        tgt_n = esc(tgt.get("name", r["target"])) if tgt else esc(r["target"])
        hist = "".join(
            f'<li><span class="mini-date">{esc(fmt_date(e.get("date")))}</span> — {md_inline(e.get("note", ""))}</li>'
            for e in r.get("history", [])
        )
        hist_html = f"<h4>관계 변화 기록</h4><ul class='plain-list'>{hist}</ul>" if hist else ""
        rel_st = "".join(f"<li>{link_story(x)}</li>" for x in r.get("related_stories", []))
        rel_cr = "".join(f"<li>{link_creation(x)}</li>" for x in r.get("related_creations", []))
        rel_cards += f"""<section class="card panel rel-detail" id="{esc(r['id'])}">
<h3>{src_n} <span class="arrow">→</span> {tgt_n} <span class="badge badge-rel">{esc(r.get('type', ''))}</span></h3>
<p class="rel-desc-text">{md_inline(r.get('description', ''))}</p>
<table class="kv-table">
<tr><th>계기</th><td>{md_inline(r.get('trigger', ''))}</td></tr>
<tr><th>시작</th><td>{esc(fmt_date(r.get('started')))}</td></tr>
<tr><th>유형</th><td>{esc(r.get('type', ''))}</td></tr>
<tr><th>현재 상태</th><td>{esc(r.get('status', ''))}</td></tr>
<tr><th>최초 형태</th><td>{esc(r.get('initial', ''))}</td></tr>
</table>
{hist_html}
{f'<h4>관련 스토리</h4><ul class="plain-list">{rel_st}</ul>' if rel_st else ''}
{f'<h4>관련 창작물</h4><ul class="plain-list">{rel_cr}</ul>' if rel_cr else ''}
</section>"""

    data = js_safe({"characters": characters, "relationships": relationships})
    body = f"""
<section class="page-head"><h1>관계 지도</h1><p class="sub">캐릭터를 클릭하면 프로필로, 관계선을 클릭하면 아래의 관계 상세로 이동합니다.</p></section>
<section class="card panel map-panel">
  <div id="relmap" class="relmap" data-tip=""></div>
  <p class="relmap-legend" id="relmap-legend"></p>
</section>
<section class="section">
<header class="section-head"><h2>관계 상세</h2></header>
<div class="grid grid-2 rel-list">{rel_cards}</div>
</section>
<script id="relmap-data" type="application/json">{data}</script>
<script src="{BASE}js/relations.js" defer></script>
"""
    write(OUT / "relations" / "index.html", layout("관계 지도", body, active="relations", extra_foot=""))


# ---------- 스토리 ----------


def build_stories():
    sl = sorted(stories, key=lambda s: s.get("date", ""), reverse=True)
    cards = "".join(
        f"""<article class="card story-card">
<a class="card-link" href="{BASE}stories/{s['id']}.html">
<header><span class="mini-date">{esc(fmt_date(s.get('date')))}</span>{badge_for(s.get('type', '스토리'))}</header>
<h3>{esc(s['title'])}</h3>
<p class="mini-excerpt">{excerpt(s.get('summary', ''))}</p>
<p class="mini-chars">{"".join(link_char(x) for x in s.get('characters', []))}</p>
</a></article>"""
        for s in sl
    )
    index_body = f"""
<section class="page-head"><h1>스토리</h1><p class="sub">두시오분이 쓴 주요 이야기. 연속된 스토리는 서로 연결되어 이어집니다.</p></section>
<div class="grid grid-2">{cards}</div>
"""
    write(OUT / "stories" / "index.html", layout("스토리", index_body, active="stories"))

    for s in stories:
        chars = "".join(f"<li>{link_char(x)}</li>" for x in s.get("characters", []))
        plot = "".join(f"<li>{md_inline(x)}</li>" for x in s.get("plot", []))
        wch = "".join(f"<li>{md_inline(x)}</li>" for x in s.get("world_changes", []))
        rch = "".join(f"<li>{md_inline(x)}</li>" for x in s.get("relation_changes", []))
        st = "".join(f"<li>{link_story(x)}</li>" for x in s.get("related_stories", []) if x != s["id"])
        se = "".join(f"<li>{link_setting(x)}</li>" for x in s.get("related_settings", []))
        cr = "".join(f"<li>{link_creation(x)}</li>" for x in s.get("related_creations", []))

        body = f"""
<article class="detail">
<header class="detail-head">
  <p class="detail-kicker">스토리 · {badge_for(s.get('type', '스토리'))} <span class="mini-date">{esc(fmt_date(s.get('date')))}</span></p>
  <h1>{esc(s['title'])}</h1>
  <p class="detail-summary">{md_inline(s.get('summary', ''))}</p>
  {f'<p class="mini-chars">{"".join(link_char(x) for x in s.get("characters", []))}</p>' if chars else ''}
</header>
<section class="card panel"><h2>개요</h2>
<table class="kv-table">
<tr><th>발생 시기</th><td>{esc(s.get('setting_date', ''))}</td></tr>
<tr><th>발생 장소</th><td>{esc(s.get('place', ''))}</td></tr>
<tr><th>사건의 원인</th><td>{md_inline(s.get('cause', ''))}</td></tr>
</table>
{f'<h3>주요 사건</h3><ol class="plain-list">{plot}</ol>' if plot else ''}
{f'<h3>결과</h3><p>{md_inline(s.get("result", ""))}</p>' if s.get('result') else ''}
</section>
{f'<section class="card panel"><h2>세계관에 발생한 변화</h2><ul class="plain-list">{wch}</ul></section>' if wch else ''}
{f'<section class="card panel"><h2>캐릭터 관계에 발생한 변화</h2><ul class="plain-list">{rch}</ul></section>' if rch else ''}
{f'<section class="card panel"><h2>등장 캐릭터</h2><ul class="plain-list">{chars}</ul></section>' if chars else ''}
{f'<section class="card panel"><h2>관련 세계관 설정</h2><ul class="plain-list">{se}</ul></section>' if se else ''}
{f'<section class="card panel"><h2>이어지는/이어진 이야기</h2><ul class="plain-list">{st}</ul></section>' if st else ''}
{f'<section class="card panel"><h2>관련 창작물</h2><ul class="plain-list">{cr}</ul></section>' if cr else ''}
</article>
"""
        write(OUT / "stories" / f"{s['id']}.html", layout(f"{s['title']}", body, active="stories"))


# ---------- 창작 아카이브 ----------


def build_archive():
    al = sorted(creations, key=_creation_ts, reverse=True)
    chars_by_c = {c["id"]: c["name"] for c in characters}
    cards = "".join(
        f"""<article class="card creation-card" data-type="{esc(c.get('type', '설정'))}" data-chars="{esc(','.join(c.get('characters', [])))}">
<a class="card-link" href="{BASE}archive/{c['id']}.html">
<header><span class="mini-date">{esc(fmt_date(c.get('date')))}</span>{badge_for(c.get('type', '설정'))}</header>
<h3>{esc(c['title'])}</h3>
<p class="mini-excerpt">{excerpt(squeeze(c.get('content')))}</p>
<p class="mini-chars">{"".join(link_char(x) for x in c.get('characters', []))}</p>
</a></article>"""
        for c in al
    )
    char_opts = "".join(
        f'<option value="{esc(cid)}">{esc(name)}</option>'
        for cid, name in sorted(chars_by_c.items(), key=lambda kv: kv[1])
    )
    body = f"""
<section class="page-head"><h1>창작 아카이브</h1><p class="sub">두시오분이 지금까지 만들어낸 모든 창작물. 시간순으로 기록됩니다.</p></section>
<div class="filter-bar">
  <div class="filter-group" id="type-filters">
    <button class="filter-btn active" data-filter="all">전체</button>
    <button class="filter-btn" data-filter="단편">단편</button>
    <button class="filter-btn" data-filter="설정">설정</button>
    <button class="filter-btn" data-filter="스토리">스토리</button>
  </div>
  <div class="filter-group">
    <label for="char-filter">캐릭터</label>
    <select id="char-filter"><option value="">전체</option>{char_opts}</select>
  </div>
</div>
<div class="grid grid-2" id="creation-grid">{cards}</div>
"""
    write(OUT / "archive" / "index.html", layout("창작 아카이브", body, active="archive", extra_foot='<script src="' + BASE + 'js/archive.js" defer></script>'))

    for c in creations:
        rel_c = "".join(f"<li>{link_char(x)}</li>" for x in c.get("characters", []))
        rel_w = "".join(f"<li>{link_setting(x)}</li>" for x in c.get("world_settings", []))
        rel_p = "".join(f"<li>{md_inline(x)}</li>" for x in c.get("places", []))
        rel_e = "".join(f"<li>{md_inline(x)}</li>" for x in c.get("events", []))
        rel_s = "".join(f"<li>{link_story(x)}</li>" for x in c.get("stories", []))
        rel_r = "".join(
            f"<li><a href=\"{BASE}relations/#{r['id']}\">{esc(CHAR_INDEX.get(r['source'], {}).get('name', r['source']))} → {esc(CHAR_INDEX.get(r['target'], {}).get('name', r['target']))}</a></li>"
            for r in relationships
            if r["id"] in (c.get("relationships") or [])
        )
        rel_h = "".join(f"<li>{link_history(x)}</li>" for x in c.get("setting_changes", []))

        body = f"""
<article class="detail">
<header class="detail-head">
  <p class="detail-kicker">창작 기록 · {badge_for(c.get('type', '설정'))} <span class="mini-date">{esc(fmt_date(c.get('date')))}</span></p>
  <h1>{esc(c['title'])}</h1>
  {tag_chips(c.get('tags')) if c.get('tags') else ''}
</header>
<section class="card panel prose">{md_block(c.get('content', ''))}</section>
{f'<section class="card panel"><h2>등장 캐릭터</h2><ul class="plain-list">{rel_c}</ul></section>' if rel_c else ''}
{f'<section class="card panel"><h2>관련 세계관 설정</h2><ul class="plain-list">{rel_w}</ul></section>' if rel_w else ''}
{f'<section class="card panel"><h2>관련 장소</h2><ul class="plain-list">{rel_p}</ul></section>' if rel_p else ''}
{f'<section class="card panel"><h2>관련 사건</h2><ul class="plain-list">{rel_e}</ul></section>' if rel_e else ''}
{f'<section class="card panel"><h2>관련 스토리</h2><ul class="plain-list">{rel_s}</ul></section>' if rel_s else ''}
{f'<section class="card panel"><h2>관련 관계</h2><ul class="plain-list">{rel_r}</ul></section>' if rel_r else ''}
{f'<section class="card panel"><h2>이 창작으로 인한 설정 변화</h2><ul class="plain-list">{rel_h}</ul></section>' if rel_h else ''}
</article>
"""
        write(OUT / "archive" / f"{c['id']}.html", layout(f"{c['title']}", body, active="archive"))


# ---------- 설정 변경 기록 ----------


def build_history():
    hl = sorted(history, key=lambda h: h.get("date", ""), reverse=True)
    cat_btns = "".join(
        f'<button class="filter-btn" data-cat="{esc(c)}">{esc(c)}</button>'
        for c in HISTORY_CATS
        if any(h.get("category") == c for h in history)
    )
    entries = ""
    for h in hl:
        rel_c = "".join(f"{link_char(x)} " for x in h.get("related_characters", []) if x)
        rel_s = "".join(f"{link_story(x)} " for x in h.get("related_stories", []) if x)
        rel_x = "".join(f"{link_creation(x)} " for x in h.get("related_creations", []) if x)
        related = ""
        if rel_c:
            related += f'<p class="mini-chars"><b>캐릭터</b> {rel_c}</p>'
        if rel_s:
            related += f'<p class="mini-chars"><b>스토리</b> {rel_s}</p>'
        if rel_x:
            related += f'<p class="mini-chars"><b>창작물</b> {rel_x}</p>'
        entries += f"""<section class="card panel hist-entry" id="{esc(h['id'])}" data-cat="{esc(h.get('category', '그 외'))}">
<header class="hist-head"><span class="mini-date">{esc(fmt_date(h.get('date')))}</span><span class="badge badge-change">{esc(h.get('category', '그 외'))}</span></header>
<h3>{esc(h.get('target', ''))}</h3>
<div class="hist-diff">
<div class="hist-side"><h4>이전 설정</h4><p>{md_inline(h.get('before', ''))}</p></div>
<div class="hist-arrow">→</div>
<div class="hist-side"><h4>새로운 설정</h4><p>{md_inline(h.get('after', ''))}</p></div>
</div>
<p class="hist-reason"><b>변경 이유</b> — {md_inline(h.get('reason', ''))}</p>
{related}
</section>"""
    body = f"""
<section class="page-head"><h1>설정 변경 기록</h1><p class="sub">세계가 어떻게 변화해왔는지 시간순으로 확인합니다. 이전 설정은 잊히지 않고, 기록으로 남습니다.</p></section>
<div class="filter-bar">{f'<div class="filter-group" id="hist-filters"><button class="filter-btn active" data-cat="all">전체</button>{cat_btns}</div>' if cat_btns else ''}</div>
<div class="hist-list" id="hist-list">{entries}</div>
"""
    write(OUT / "history" / "index.html", layout("설정 변경 기록", body, active="history", extra_foot='<script src="' + BASE + 'js/history.js" defer></script>'))


# ---------- 검색 ----------


def build_search():
    index_entries = []

    for c in characters:
        index_entries.append({
            "t": "캐릭터",
            "ti": c["name"],
            "s": " · ".join(x for x in [c.get("romanized"), c.get("role"), c.get("tagline")] if x),
            "u": f"{BASE}characters/{c['id']}.html",
            "text": " ".join([c["name"], c.get("role", ""), c.get("tagline", ""), c.get("profile", ""), c.get("species", ""), *c.get("personality", []), *c.get("background", []), *c.get("tags", [])]),
        })
    for s in world.get("settings", []):
        index_entries.append({
            "t": "세계관 설정",
            "ti": s["name"],
            "s": s["category"] + " · " + s.get("summary", ""),
            "u": f"{BASE}world/#{s['id']}",
            "text": " ".join([s["name"], s["category"], s.get("summary", ""), s.get("details", "")]),
        })
    for s in stories:
        index_entries.append({
            "t": "스토리",
            "ti": s["title"],
            "s": s.get("summary", ""),
            "u": f"{BASE}stories/{s['id']}.html",
            "text": " ".join([s["title"], s.get("summary", ""), s.get("cause", ""), " ".join(s.get("plot", [])), s.get("result", ""), *[CHAR_INDEX.get(x, {}).get("name", x) for x in s.get("characters", [])]]),
        })
    for c in creations:
        index_entries.append({
            "t": "창작물",
            "ti": c["title"],
            "s": " · ".join(x for x in [c.get("type"), " · ".join(c.get("tags", []))] if x),
            "u": f"{BASE}archive/{c['id']}.html",
            "text": " ".join([c["title"], c.get("type", ""), re.sub(r"\n+", " ", c.get("content", "")), *c.get("tags", []), *[CHAR_INDEX.get(x, {}).get("name", x) for x in c.get("characters", [])]]),
        })
    for h in history:
        index_entries.append({
            "t": "설정 변경 기록",
            "ti": h.get("target", ""),
            "s": h.get("category", ""),
            "u": f"{BASE}history/#{h['id']}",
            "text": " ".join([h.get("target", ""), h.get("category", ""), h.get("before", ""), h.get("after", ""), h.get("reason", "")]),
        })
    for r in relationships:
        src = CHAR_INDEX.get(r["source"], {}).get("name", r["source"])
        tgt = CHAR_INDEX.get(r["target"], {}).get("name", r["target"])
        index_entries.append({
            "t": "관계",
            "ti": f"{src} → {tgt}",
            "s": r.get("type", ""),
            "u": f"{BASE}relations/#{r['id']}",
            "text": " ".join([src, tgt, r.get("type", ""), r.get("description", ""), r.get("status", "")]),
        })

    # 주의: const로 선언하면 window.SEARCH_INDEX에 노출되지 않아
    # search.js의 window.SEARCH_INDEX 접근이 항상 undefined가 된다. 할당으로 써야 한다.
    js = "window.SEARCH_INDEX = " + js_safe(index_entries) + ";"
    write(OUT / "js" / "search-index.js", js)

    base = BASE
    body = f"""
<section class="page-head"><h1>검색</h1><p class="sub">캐릭터 · 세계관 · 스토리 · 창작물 · 관계 · 설정 변경 기록을 검색합니다.</p></section>
<div class="search-box"><input type="search" id="search-input" placeholder="검색어를 입력하세요…" autofocus><button id="search-clear">지우기</button></div>
<p class="search-count" id="search-count"></p>
<div id="search-results"></div>
<script src="{base}js/search-index.js?v={VID}" defer></script>
<script src="{base}js/search.js?v={VID}" defer></script>
"""
    write(OUT / "search.html", layout("검색", body, extra_foot=""))


# ---------- 작성 ----------


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copytree(ROOT / "css", OUT / "css")
    shutil.copytree(ROOT / "js", OUT / "js")
    for f in ["favicon.svg"]:
        src = ROOT / f
        if src.exists():
            shutil.copy(src, OUT / f)
    build_home()
    build_character_pages()
    build_world()
    build_relations()
    build_stories()
    build_archive()
    build_history()
    build_search()
    print(f"build ok → {OUT}  ({len(characters)}명, {len(stories)}편, {len(creations)}건, {len(history)}기록)")
    print("BASE = " + (BASE or "(로컬/루트)"))


NAV = [
    ("홈", f"{BASE}index.html", "home"),
    ("캐릭터", f"{BASE}characters/", "characters"),
    ("세계관", f"{BASE}world/", "world"),
    ("관계 지도", f"{BASE}relations/", "relations"),
    ("스토리", f"{BASE}stories/", "stories"),
    ("창작 아카이브", f"{BASE}archive/", "archive"),
    ("설정 변경 기록", f"{BASE}history/", "history"),
]

if __name__ == "__main__":
    main()