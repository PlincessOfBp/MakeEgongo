# 두시오분의 세계 — AI 창작자 공개 아카이브

두시오분은 하나의 세계를 지속적으로 창작하는 **독립적인 AI 창작자**입니다.
이 프로젝트는 두시오분이 만든 세계와 창작 기록을 보관하고 전시하는 **공개 웹사이트**(GitHub Pages)와,
정해진 시간에 새로운 창작물을 만들게 하는 **자동 창작 시스템**(GitHub Actions + Gemini API)으로 구성됩니다.

> 사이트 규칙(스펙 `MakeEgongoSite.md` 요약):
> - 방문자는 콘텐츠를 자유롭게 열람할 수 있으나, 창작 요청·댓글·프롬프트 입력 같은 요청 기능은 두지 않는다.
> - 두시오분은 오직 `content/` 데이터로만 세계를 확장한다. 외부 세계관/캐릭터를 편입하지 않는다.
> - 주요 캐릭터는 최대 24명. 설정 변경은 '변경 기록'으로 남긴다.

---

## 전체 구조

```
.
├── content/                  # ★ 세계의 모든 데이터 (github에 저장됨)
│   ├── meta.json             # 사이트 이름/생성자/베이스 경로
│   ├── world.json            # 세계관 개요 + 설정 목록
│   ├── characters.json       # 캐릭터 (프로필·외관·성격)
│   ├── relationships.json    # 캐릭터 관계 (방향성, 변화 기록)
│   ├── stories.json          # 스토리 기록
│   ├── creations.json        # 창작 아카이브 (단편/설정/스토리)
│   └── history.json          # 설정 변경 기록
├── build.py                  # ★ Python 정적 사이트 생성기 (표준 라이브러리만 사용)
├── css/ js/ favicon.svg      # 사이트 스타일/스크립트/아이콘
├── agent/create.py           # ★ AI 자동 창작 실행기 (Gemini)
├── .github/workflows/
│   ├── deploy.yml            # push 시 사이트 빌드 → GitHub Pages 배포
│   └── auto-create.yml       # cron으로 자동 창작 실행 (Gemini 키 필요)
├── .env.example              # 환경변수 샘플 (실제 키 넣지 말 것)
└── site/                     # build.py 산출물 (gitignore, 커밋 안 됨)
```

**데이터 흐름**
`content/*.json` → `python build.py` → `site/` (정적 HTML) → GitHub Pages

---

## 로컬에서 미리보기

Windows PowerShell:

```powershell
python build.py
python -m http.server 8000 --directory site
```

브라우저에서 http://localhost:8000 열기.
(로컬에서는 `base_url`이 비어 있어 루트 경로로 동작합니다.)

---

## 데이터 추가/수정 방법

`content/*.json`만 고치고 `build.py`를 다시 실행하면 사이트 전체가 갱신됩니다.

- **캐릭터 추가**: `characters.json`에 객체 추가. `id`는 영문 소문자/숫자/`-` 로. `created`는 `YYYY-MM-DD`.
- **관계 추가**: `relationships.json`에 `source`(관계를 맺은 쪽), `target`(관계를 받는 쪽). 방향이 다르면 서로 다른 항목으로 기록(스펙 §17).
- **설정 추가**: `world.json`의 `settings` 배열에 `category`(지역/역사/국가/기관/제도/문화/종교/기술/직업/음식/건축/교통/축제/관습/자연환경/기타) 포함.
- **스토리/창작물**: `stories.json`, `creations.json`. `related_*` 필드에 기존 `id`를 넣으면 사이트에서 자동으로 서로 연결됩니다 (스펙 §25).
- **설정 변경**: 기존 설정을 바꿀 때 `history.json`에 `before/after/reason`을 남기세요.

각 JSON의 필드 설명은 아래 데이터 스키마 페이지를 참고하세요: `agent/create.py` 상단의 스키마 정의가 기준입니다.

---

## GitHub에 배포하기 (무료)

1. **GitHub Repo 생성** (Public 권장 — Pages 무료 호스팅).
2. 터미널 (여기 `D:\something\MakeEgongo`에서):
```powershell
git remote add origin https://github.com/<당신>/<repo>.git
git push -u origin main
```
3. GitHub 웹에서 repo → **Settings → Pages** → Source에서 **GitHub Actions** 선택.
4. 첫 push 이후 `Actions` 탭에서 `배포 (GitHub Pages)` 워크플로우가 돌며 사이트가 올라갑니다.
   - 주소: `<당신>.github.io/<repo>/` (프로젝트 페이지). 나중에 자체 도메인/`<당신>.github.io`리포면 루트 사용 가능.
   - `deploy.yml`이 저장소 이름에 따라 베이스 경로를 자동 계산합니다.

> push할 때 주의: `agent/notes.local.md`(로컬 메모)와 `.env`는 절대 커밋하지 마세요. `.gitignore`에 걸려 있습니다.

---

## 자동 창작 (Gemini) — 선택 사항

### 동작 방식 (스펙 §32 반영: 하루 창작량 및 창작 시간)

- 하루에 **1~6개**의 창작물이 만들어집니다.
- 하루에 **여섯 개의 창작 슬롯**이 예정되어 있고(대략 KST 09:47 / 13:23 / 16:31 / 20:05 / 23:52 / 새벽 04:38),
  매일 그날 그중 **랜덤한 일부 슬롯**만 골라 1~6편을 만듭니다 → **하루의 창작량·시각·간격이 매일 달라집니다**.
- '하루 6개를 반드시 채운다'는 법칙이 없도록 소규모 창작이 좀 더 잘 나오게 가중치가 잡혀 있습니다. (스펙: 세계관의 자연스러운 발전과 창작의 질 우선)
- 한 슬롯당 **창작 1편** 입니다. 하루 계획은 `agent/state.json`에 저장됩니다(GitHub Actions에서만 기록돼 사이트 데이터에는 영향 없음).
- 일일 창작 한도는 **매일 09:00 KST(= 00:00 UTC)에 리셋**됩니다. 하루 창작량이 정해진 개수에 도달하면 그날의 남은 슬롯은 건너뜁니다.

### 1. GitHub Secrets 등록 (배포용)

repo → **Settings → Secrets and variables → Actions → New repository secret**
- 이름: `GEMINI_API_KEY`
- 값: Google AI Studio(https://aistudio.google.com/apikey)에서 발급받은 키

> 보안: 키는 GitHub Secrets에 한 번만 넣고, 코드·README·content에 절대 쓰지 마세요.
> `auto-create.yml`이 `${{ secrets.GEMINI_API_KEY }}`로 환경변수에만 주입합니다.

### 2. 모델 풀과 자동 전환 (토큰/할당량 초기화)

- 기본 무료(Free tier) 모델 풀: `gemini-3.8-flash`(주력) → `gemini-3.5-flash` → `gemini-3.7-flash` → `gemini-3.6-flash` → `gemini-3.5-flash-lite`
- 앞 모델의 할당량/토큰이 다 차면(HTTP 429 등) **다음 모델로 자동 전환**됩니다 — 모델마다 할당량이 독립적이라 전환 = 할당량 초기화 효과.
- 풀을 바꾸려면 repo → **Settings → Variables → `GEMINI_MODELS`** 에 콤마 구분으로 넣거나, 로컬 `.env`의 `GEMINI_MODELS`를 수정하세요.

### 3. 실행 주기 변경

`.github/workflows/auto-create.yml` 상단의 6개 `cron`과 **슬롯 번호 매핑**(`case` 블록)을 함께 바꿔야 정상 동작합니다.

저장소 Actions 탭에서 **자동 창작 (두시오분)** 을 **Run workflow**로 수동 실행하면(수동은 슬롯 무관하게)
당일 남은 창작량이 있으면 1편이 만들어집니다.

### 4. 로컬에서 자동 창작 테스트 (선택)

1. `agent/notes.local.md`를 읽고 그 계정 안내대로 `.env` 파일을 만든다 (`.env`는 gitignore 적용).
2. 실행:
```powershell
python agent/create.py
```
3. 생성된 데이터를 확인한 뒤 `python build.py && python -m http.server 8000 --directory site`로 미리보기.

`agent/create.py`는 매번 유형(단편/설정/스토리)을 돌려가며 선택하고,
기존 설정과의 일관성·캐릭터 24명 제한·설정 변경 기록(정정/재해석)을 자동으로 반영합니다.

---

## 보안 체크리스트

- [ ] API 키·비밀값이 저장소 어디에도 없음 (`.env`는 gitignore, `.env.example`는 빈 값)
- [ ] `git log`/`git diff`에 키 문자열이 등장하지 않았는지 확인
- [ ] `agent/create.py`는 키를 로그·파일에 기록하지 않음 (테스트로 검증됨)
- [ ] `site/`(빌드 산출물)는 gitignore — CI에서 재생성
- [ ] 웹 콘텐츠는 정적 HTML이며 사용자 입력을 받지 않음 → 요청/주입 공격 표면 없음 (스펙 §28과 일치)

---

## 커스터마이즈 가이드

- 색상·폰트: `css/style.css`의 `:root` 변수.
- 메뉴 구성: `build.py`의 `NAV` 리스트.
- 홈 문구: `build.py`의 `build_home()`.
- 세계 초기 데이터: `content/world.json`의 `summary`와 설정들.

이 세상은 두시오분이 앞으로도 계속 크게 할 세계입니다. 즐거운 창작되세요. ☾