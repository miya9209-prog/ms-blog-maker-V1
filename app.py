import re
import html
from datetime import datetime
from typing import List, Tuple, Optional

import streamlit as st

# OpenAI
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# =========================================================
# Utils
# =========================================================
def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def keywords_from_csv(csv_text: str) -> List[str]:
    if not csv_text:
        return []
    items = [x.strip() for x in csv_text.split(",")]
    items = [x for x in items if x]
    seen = set()
    out = []
    for it in items:
        k = it.lower()
        if k not in seen:
            out.append(it)
            seen.add(k)
    return out


def safe_slug_10chars(title: str) -> str:
    t = re.sub(r"\s+", "", title or "")
    t = re.sub(r"[^\w가-힣]", "", t)
    return (t[:10] if t else "블로그글")


def normalize_spaces(s: str) -> str:
    # 콜론 띄어쓰기: "단어: 값"
    s = re.sub(r"([가-힣A-Za-z0-9])\s*:\s*", r"\1: ", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def strip_title_prefix(line: str) -> str:
    l = (line or "").strip()
    l = re.sub(r"^(제목\s*[:：]\s*)", "", l)
    l = re.sub(r"^(\[제목\]\s*)", "", l)
    l = re.sub(r"^(TITLE\s*[:：]\s*)", "", l, flags=re.IGNORECASE)
    return l.strip()


def split_title_and_body(generated: str, fallback_title: str) -> Tuple[str, str]:
    txt = (generated or "").strip()
    if not txt:
        return fallback_title, ""

    lines = txt.splitlines()

    title_idx = None
    for i, ln in enumerate(lines):
        if ln.strip():
            title_idx = i
            break

    if title_idx is None:
        return fallback_title, txt

    title = strip_title_prefix(lines[title_idx])
    if len(title) < 4 or len(title) > 90:
        title = fallback_title

    body = "\n".join(lines[title_idx + 1:]).strip()
    return title, body


def fix_url_spacing(url: str) -> str:
    u = (url or "").strip()
    u = re.sub(r"https:\s*//", "https://", u)
    u = re.sub(r"http:\s*//", "http://", u)
    return u


def ensure_hashtags_30(required: List[str], keywords: List[str]) -> str:
    base = []
    seen = set()

    def add(tag: str):
        t = (tag or "").strip()
        if not t:
            return
        if not t.startswith("#"):
            t = "#" + t
        k = t.lower()
        if k in seen:
            return
        seen.add(k)
        base.append(t)

    for t in required:
        add(t)

    for k in keywords:
        k2 = re.sub(r"\s+", "", k)
        if k2:
            add("#" + k2)

    filler = [
        "#겨울코디", "#봄코디", "#간절기코디", "#오피스룩", "#하객룩", "#학교상담룩",
        "#체형커버", "#데일리패션", "#중년코디", "#미시룩", "#심플룩", "#꾸안꾸",
        "#스타일링", "#코디추천", "#여성패션", "#쇼핑몰추천", "#오늘의코디", "#데일리코디",
        "#40대코디", "#50대코디", "#중년여성"
    ]
    for t in filler:
        if len(base) >= 30:
            break
        add(t)

    return " ".join(base[:30])


def ensure_markdown_tables(text: str) -> str:
    """
    모델이 표를 텍스트로 뭉개서 주는 경우를 일부 보정.
    (완전한 파서까지는 과하지만, 흔한 케이스를 커버)
    """
    t = text or ""

    # 케이스: "어깨단면: 50 | 가슴둘레: 117 | ..." -> 2열 표로 변환
    m = re.search(r"아이템 사이즈 스펙.*?\n(.*?:\s*\d+.*\|.*)", t, flags=re.DOTALL)
    # 위 패턴이 애매해서, 그냥 본문 전체에서 "xxx: 값 | yyy: 값" 라인들만 감지
    lines = t.splitlines()
    out = []
    for ln in lines:
        if "|" in ln and re.search(r"[가-힣A-Za-z]+\s*:\s*[^|]+", ln):
            parts = [p.strip() for p in ln.split("|") if p.strip()]
            # 2열 표(항목/값)로 바꿔붙이기
            rows = []
            ok = True
            for p in parts:
                mm = re.match(r"^(.+?)\s*:\s*(.+)$", p)
                if not mm:
                    ok = False
                    break
                rows.append((mm.group(1).strip(), mm.group(2).strip()))
            if ok and len(rows) >= 2:
                tbl = ["| 항목 | 값 |", "|---|---|"]
                for a, b in rows:
                    tbl.append(f"| {a} | {b} |")
                out.extend(tbl)
                continue
        out.append(ln)
    return "\n".join(out)


def markdown_to_simple_html(md_text: str) -> str:
    """
    복사용은 마크다운이 메인.
    HTML 다운로드는 '간단 래핑'만 제공(완전 변환은 지양).
    """
    escaped = html.escape(md_text or "")
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>미샵 블로그 글</title>
</head>
<body>
<pre style="white-space:pre-wrap; font-family:system-ui, -apple-system, Segoe UI, Roboto, Apple SD Gothic Neo, Noto Sans KR, sans-serif;">
{escaped}
</pre>
</body>
</html>
"""


# =========================================================
# OpenAI Call
# =========================================================
def get_openai_client() -> Tuple[Optional["OpenAI"], str, str]:
    api_key = str(st.secrets.get("OPENAI_API_KEY", "")).strip() if hasattr(st, "secrets") else ""
    model = str(st.secrets.get("OPENAI_MODEL", "gpt-4.1-mini")).strip() if hasattr(st, "secrets") else "gpt-4.1-mini"

    # UnicodeEncodeError 방지(숨은 문자/스마트따옴표 등)
    if any(ord(ch) > 127 for ch in api_key):
        return None, model, "OPENAI_API_KEY에 비ASCII(숨은 문자)가 포함되어 있습니다. Secrets에서 키를 다시 붙여넣어 주세요(일반 쌍따옴표 \")."

    if not api_key or OpenAI is None:
        return None, model, "OpenAI 라이브러리 또는 API 키가 없습니다."
    return OpenAI(api_key=api_key), model, ""


def call_openai_text(prompt: str) -> str:
    client, model, err = get_openai_client()
    if client is None:
        return "(테스트 모드) OpenAI 호출 불가.\n\n" + err + "\n\n" + prompt[:1800]
    resp = client.responses.create(model=model, input=prompt)
    return resp.output_text


def needs_rewrite_to_prose(text: str) -> bool:
    lines = (text or "").splitlines()
    bullet_like = sum(1 for ln in lines if ln.strip().startswith(("-", "•")) or re.match(r"^\s*\d+\)", ln))
    return bullet_like >= 10


def rewrite_to_prose(platform: str, product_name: str, text: str) -> str:
    prompt = f"""
너는 20년차 여성의류 쇼핑몰 미샵 대표이며, 블로그 글을 ‘문장형 서사’로 고쳐 쓰는 편집자다.

[목표]
- 아래 원문을 ‘블로그다운 문장형’으로 재작성한다.
- 리스트(불릿)는 오직 2개 섹션에서만 허용:
  1) "이런 분들께 추천합니다"
  2) "이럴 때 요긴해요"
- 그 외 섹션은 불릿/번호 나열 금지. 반드시 문단(2~4문장)으로 풀어쓴다.
- 표는 반드시 ‘마크다운 표’로 출력한다.
  (| 컬럼 | 컬럼 | 형태, 헤더/구분선 포함)
- 마지막 줄 해시태그 30개는 한 줄로 유지한다.
- 플랫폼: {platform}
- 상품명: {product_name}

[원문]
{text}

[출력 형식]
- 1행 제목
- 빈 줄
- 본문(마크다운)
- 맨 마지막 줄 해시태그 30개
""".strip()
    out = call_openai_text(prompt)
    return out


# =========================================================
# Prompts
# =========================================================
def platform_profile(platform_label: str) -> str:
    if platform_label.startswith("네이버"):
        return """
[네이버 최적화]
- 공감/대화 리듬으로 체류시간을 올린다.
- 문단은 2~4문장, 중간중간 ‘현장 멘트’로 숨을 준다.
- 키워드는 억지 반복 금지. 자연스럽게 분산.
"""
    if platform_label.startswith("티스토리"):
        return """
[티스토리(다음/카카오) 최적화]
- 소제목으로 흐름을 정리하되, 본문은 문장형으로 풀어쓴다.
- ‘문제→해결→추천’ 흐름이 드러나게.
- 키워드는 자연스럽게 8~12회 분산.
"""
    return """
[블로거(구글) 최적화]
- E-E-A-T: 20년차 대표의 관찰/현장 경험/고객 반응을 근거로.
- 소제목(H2/H3 느낌)은 명확히, 본문은 문장형으로.
- 동의어/연관어로 자연 확장(반복 키워드 남발 금지).
"""


def build_misharp_prompt_narrative(
    platform: str,
    product_name: str,
    primary_kw: str,
    keywords: List[str],
    user_notes: str,
    product_url: str,
    size_spec_text: str,
    reviews_text: str,
) -> str:
    kws_joined = ", ".join(keywords) if keywords else ""
    product_url = fix_url_spacing(product_url)

    if reviews_text.strip():
        reviews_rule = "후기 텍스트를 과장 없이 요약하되, 실제 반응 중심으로 6~10줄 문장형으로 정리하라."
    else:
        reviews_rule = "후기 텍스트가 비어 있으면 ‘고객 후기 반응 요약’ 섹션을 절대 쓰지 마라."

    return f"""
너는 20년차 여성의류 쇼핑몰 미샵(MISHARP) 대표이며,
4050 여성 고객을 매일 상담해온 현장형 MD다.
이 글은 ‘마크다운으로 쓰는 블로그 상담 글’이다.

{platform_profile(platform)}

[절대 규칙]
1) 첫 문장은 반드시 아래 그대로 시작:
안녕하세요^^ 일상도 스타일도 미샵처럼 심플하게! 20년차 여성의류 쇼핑몰 미샵 대표입니다.
2) 두 번째 문장은 반드시 계절/날씨/시기 공감 + 옷장 앞 고민을 넣어라.
3) 말투: 존댓말 기본. 대중적/캐주얼. 때로 쇼핑호스트, 때로 동네 옷가게 사장님 톤.
4) 구분선(---, ===) 금지. 문단 연결 문장으로 자연스럽게 이어라.
5) 콜론 표기: “단어: 값” 한 칸 띄어쓰기.
6) 분량: 4,000~5,000자 내외.
7) 마지막 줄: “일상도 스타일도 미샵처럼, 심플하게! MISHARP”
8) 해시태그 30개는 맨 끝 한 줄.

[마크다운 출력 규칙(중요)]
- 본문 전체는 마크다운으로 작성한다.
- 표 2개(사이즈 스펙/사이즈 추천)는 반드시 ‘마크다운 표’로 출력한다:
  예)
  | 항목 | 값 |
  |---|---|
  | 어깨단면 | 50 |
- 표 이외에는 마크다운 리스트를 과도하게 쓰지 말 것.

[문장형 규칙]
- 리스트(불릿)는 오직 2개 섹션에서만 허용:
  A) 이런 분들께 추천합니다
  B) 이럴 때 요긴해요
- 그 외 모든 섹션에서는 불릿/번호 나열 금지.
  반드시 문단(2~4문장)으로 풀어쓴다.
- 아래 현장 멘트를 본문 중 최소 2회 자연스럽게 포함:
  “고객님들이 제일 많이 하시는 말이요.”
  “제가 20년 하면서 확실히 느낀 건데요.”
  “여기서 포인트는 딱 하나예요.”

[SEO 규칙]
- 제목: 30~35자 권장. 반드시 “[미샵]” 포함. 상위 키워드 1개 포함: {primary_kw}
- 본문 자연 삽입(억지 금지): 미샵, 여성의류, 40대여성의류, 50대여성의류, 출근룩, 데일리룩
- 키워드({kws_joined})는 문맥 속 자연스럽게 분산(총 8~12회 느낌), 나열/반복 금지.

[구성(순서 유지)]
1) 제목(1줄만)
2) 최상단 요약 3~5줄(문장형)
3) 공감 도입(생활 장면 2~3개 + 왜 이 옷이 필요한지)
4) 이런 분들께 추천합니다(불릿 5~7개)  ← 여기만 리스트 허용
5) 이럴 때 요긴해요(불릿 5~7개)        ← 여기만 리스트 허용
6) (자연스러운 제목) 입었을 때 ‘정돈되는’ 느낌(디자인/핏: 문장형 2~3문단)
7) (자연스러운 제목) 하루가 편해지는 이유(소재/착용감: 문장형 2~3문단)
8) (자연스러운 제목) 결국 손이 가는 옷의 조건(가치/가격: 문장형 1~2문단)
9) 고객 후기 반응 요약(조건): {reviews_rule}
10) 활용성/코디 제안(TPO 연결: 문장형 2~3문단)
11) (자연스러운 제목) 이 아이템, 꼭 만나보세요(공감 CTA: 문장형 1문단)
12) 아이템 사이즈 스펙 표(마크다운 표 1개)
13) 사이즈 추천 표(마크다운 표 1개)
14) 최하단 요약 3줄(문장형)
15) 인용박스(>) CTA 2~3줄
16) 슬로건 + 해시태그 30개(한 줄)

[입력 정보]
- 상품명: {product_name}
- 상품 URL: {product_url}
- 핵심 키워드: {kws_joined}

- 사용자 메모/원고:
{user_notes}

- 사이즈 스펙(표 재료):
{size_spec_text}

- 후기 텍스트:
{reviews_text}

[출력 형식(강제)]
- 1행: 제목만(“제목:” 접두어 금지)
- 2행: 빈 줄
- 3행부터: 본문(마크다운)
- 맨 마지막 줄: 해시태그 30개 한 줄
""".strip()


def build_general_prompt(platform: str, topic: str, keywords: List[str], notes: str) -> str:
    kws_joined = ", ".join(keywords) if keywords else ""
    return f"""
너는 {platform} SEO에 최적화된 블로그 글을 쓰는 전문가다.
분량: 약 4,000~5,000자.
키워드({kws_joined})는 억지 반복 금지, 자연스럽게 분산.
출력은 마크다운으로 한다(표가 필요하면 마크다운 표 사용).

{platform_profile(platform)}

[글 시작 고정]
안녕하세요, 000입니다. (시기적으로 적절한 인삿말) 오늘은 ({topic})에 대해 얘기해볼까해요.

[필수 구성]
- 최상단 글요약 3~5줄
- 주제 관련 일상적 공감 문제 제기/공감 유도
- 본문(문단별 소제목, 정보+경험+예시 혼합)
- 마지막 요약 3줄
- 해시태그 30개(한 줄)
- 마지막 인사(창작): “오늘 정보가 도움이 되었으면 합니다” 취지

[입력 메모]
{notes}

[출력 형식]
- 1행: 제목만(접두어 금지)
- 2행: 빈 줄
- 3행부터: 본문(마크다운)
- 맨 마지막 줄: 해시태그 30개 한 줄
""".strip()


# =========================================================
# UI / Style
# =========================================================
st.set_page_config(page_title="미샵 블로그글 생성기", page_icon="📝", layout="wide")

st.markdown(
    """
<style>
  .block-container { padding-top: 1.8rem; padding-bottom: 2.2rem; max-width: 1180px; }
  h1 { font-size: 2.05rem !important; letter-spacing: -0.02em; }
  .subcap { margin-top: -6px; color: rgba(255,255,255,0.65); font-size: 0.95rem; }
  .card {
    padding: 18px 18px 14px 18px;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 16px;
    background: rgba(255,255,255,0.03);
    margin-bottom: 14px;
  }
  .step-title {
    font-size: 1.05rem;
    font-weight: 700;
    margin-bottom: 10px;
    letter-spacing: -0.01em;
  }
  .hint {
    color: rgba(255,255,255,0.65);
    font-size: 0.92rem;
    margin-top: -6px;
    margin-bottom: 10px;
  }
  .footer {
    margin-top: 56px;
    padding-top: 18px;
    border-top: 1px solid rgba(255,255,255,0.08);
    font-size: 0.78rem;
    line-height: 1.55;
    color: rgba(255,255,255,0.45);
    text-align: center;
  }
</style>
""",
    unsafe_allow_html=True,
)

st.title("📝 미샵 블로그글 생성기")
st.markdown('<div class="subcap">블로그 선택 → 주제 입력 → 글 생성(마크다운 표 지원) → 이미지/발행</div>', unsafe_allow_html=True)

left, right = st.columns([1.05, 1.0], gap="large")

with left:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="step-title">1) 블로그 선택</div>', unsafe_allow_html=True)
    platform = st.radio(
        "플랫폼",
        ["네이버(네이버 SEO)", "티스토리(다음/카카오 SEO)", "블로거(구글 SEO)"],
        horizontal=True,
        label_visibility="collapsed",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="step-title">2) 주제 입력</div>', unsafe_allow_html=True)
    post_type = st.selectbox("글 유형", ["미샵 패션 아이템 글", "기타 주제 글"])

    c1, c2 = st.columns([1, 1], gap="small")
    with c1:
        product_url = st.text_input("상품 URL(선택)", placeholder="https://misharp.co.kr/product/detail.html?product_no=...")
    with c2:
        topic_text = st.text_input("주제/상품명(필수)", placeholder="예) 트루 피치 체크 셔츠 / 40대 출근룩 코디")

    kw_csv = st.text_input("키워드(','로 구분)", placeholder="예) 출근룩, 데일리룩, 체형커버, 간절기셔츠, 여성셔츠")
    keywords = keywords_from_csv(kw_csv)

    notes = st.text_area("내용 입력(상세설명/원고/메모)", height=220)

    if post_type == "미샵 패션 아이템 글":
        with st.expander("추가 입력(선택): 사이즈/후기", expanded=False):
            size_spec_text = st.text_area("사이즈 스펙(표 재료)", height=120)
            reviews_text = st.text_area("후기 텍스트(있으면 붙여넣기)", height=120)
    else:
        size_spec_text = ""
        reviews_text = ""

    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="step-title">3) 글 생성</div>', unsafe_allow_html=True)
    st.markdown('<div class="hint">생성 후 4)에서 “미리보기(표 렌더)” + “복사용 원문(마크다운)”을 제공합니다.</div>', unsafe_allow_html=True)

    enhance_prose = st.checkbox("문장형 강화(자동 보정)", value=True)

    if st.button("✨ 글 생성하기", type="primary", use_container_width=True):
        if not topic_text.strip():
            st.error("주제/상품명(필수)을 입력해주세요.")
            st.stop()

        primary_kw = keywords[0] if keywords else (topic_text.strip().split()[0] if topic_text.strip() else "여성의류")

        if post_type == "미샵 패션 아이템 글":
            prompt = build_misharp_prompt_narrative(
                platform=platform,
                product_name=topic_text.strip(),
                primary_kw=primary_kw,
                keywords=keywords,
                user_notes=notes.strip(),
                product_url=product_url.strip(),
                size_spec_text=size_spec_text.strip(),
                reviews_text=reviews_text.strip(),
            )
        else:
            prompt = build_general_prompt(
                platform=platform,
                topic=topic_text.strip(),
                keywords=keywords,
                notes=notes.strip(),
            )

        raw = call_openai_text(prompt)
        raw = normalize_spaces(raw)

        if enhance_prose and post_type == "미샵 패션 아이템 글" and needs_rewrite_to_prose(raw):
            raw = rewrite_to_prose(platform, topic_text.strip(), raw)
            raw = normalize_spaces(raw)

        title_guess, body = split_title_and_body(raw, fallback_title=topic_text.strip())

        if post_type == "미샵 패션 아이템 글":
            required = ["#미샵", "#여성의류", "#출근룩", "#데일리룩", "#ootd", "#40대여성의류", "#50대여성의류", "#중년여성패션"]
        else:
            required = []

        tags_line = ensure_hashtags_30(required, keywords)

        body = re.sub(r"(#\S+\s*){8,}$", "", body, flags=re.MULTILINE).rstrip()
        full_md = (title_guess + "\n\n" + body).strip() + "\n\n" + tags_line

        # 표 형태 보정(일부 케이스)
        full_md = ensure_markdown_tables(full_md)

        st.session_state["generated_title"] = title_guess
        st.session_state["generated_md"] = full_md
        st.success("생성 완료! 아래 5)에서 복사/다운로드 하세요.")

    st.markdown("</div>", unsafe_allow_html=True)

    # 4) 결과: ChatGPT처럼 "렌더링 + 원문" 제공
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="step-title">5) 결과 / 복사 / 다운로드</div>', unsafe_allow_html=True)

    if "generated_md" not in st.session_state:
        st.info("아직 생성된 글이 없습니다. 위에서 **3) 글 생성하기**를 눌러주세요.")
    else:
        title_guess = st.session_state.get("generated_title", "미샵 블로그 글")
        md_text = st.session_state["generated_md"]

        tab1, tab2, tab3 = st.tabs(["미리보기(표 그대로)", "복사용 원문(마크다운)", "다운로드/HTML"])

        with tab1:
            st.markdown(md_text)

        with tab2:
            st.text_area("여기 내용을 그대로 복사해서 사용하세요(표 포함)", value=md_text, height=420)

        with tab3:
            fname_base = f"{today_yyyymmdd()}_{safe_slug_10chars(title_guess)}"
            st.download_button(
                "⬇️ MD 다운로드(표 유지 추천)",
                data=md_text,
                file_name=f"{fname_base}.md",
                mime="text/markdown",
                use_container_width=True,
            )
            st.download_button(
                "⬇️ TXT 다운로드",
                data=md_text,
                file_name=f"{fname_base}.txt",
                mime="text/plain",
                use_container_width=True,
            )

            html_doc = markdown_to_simple_html(md_text)
            st.markdown("**HTML(간단 래핑) — 필요 시 사용**")
            st.code(html_doc, language="html")
            st.download_button(
                "⬇️ HTML 다운로드",
                data=html_doc,
                file_name=f"{fname_base}.html",
                mime="text/html",
                use_container_width=True,
            )

    st.markdown("</div>", unsafe_allow_html=True)

    # 5) 이미지 생성
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="step-title">3) 이미지 생성</div>', unsafe_allow_html=True)
    st.link_button("🖼️ 미샵 상세페이지 이미지 추출기(자동 ZIP)", "https://misharp-image-crop-v1.streamlit.app/", use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.link_button("Pexels (무료)", "https://www.pexels.com/ko-kr/", use_container_width=True)
    with c2:
        st.link_button("Pixabay (무료)", "https://pixabay.com/ko/", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # 6) 발행하기
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="step-title">4) 발행하기</div>', unsafe_allow_html=True)
    b1, b2, b3 = st.columns(3)
    with b1:
        st.link_button("네이버 블로그 로그인", "https://nid.naver.com/nidlogin.login", use_container_width=True)
    with b2:
        st.link_button("티스토리 로그인", "https://www.tistory.com/auth/login", use_container_width=True)
    with b3:
        st.link_button("Blogger 로그인", "https://accounts.google.com/signin/v2/identifier?service=blogger", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

# Footer
st.markdown(
    """
<div class="footer">
ⓒ 미샵컴퍼니(MISHARP COMPANY). 본 콘텐츠의 저작권은 미샵컴퍼니에 있으며,
무단 복제·배포·전재·2차 가공 및 상업적 이용을 금합니다.<br/>
ⓒ MISHARP COMPANY. All rights reserved. Unauthorized copying, redistribution,
republication, modification, or commercial use is strictly prohibited.
</div>
""",
    unsafe_allow_html=True,
)
