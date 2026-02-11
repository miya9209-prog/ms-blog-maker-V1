import re
import html
from datetime import datetime
from typing import List, Tuple, Optional

import streamlit as st
import streamlit.components.v1 as components

# OpenAI (Responses API)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# =========================================================
# Basic Utils
# =========================================================
def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def fix_url_spacing(url: str) -> str:
    u = (url or "").strip()
    u = re.sub(r"https:\s*//", "https://", u)
    u = re.sub(r"http:\s*//", "http://", u)
    return u


def normalize_spaces(s: str) -> str:
    # 콜론 띄어쓰기: "단어: 값"
    s = re.sub(r"([가-힣A-Za-z0-9])\s*:\s*", r"\1: ", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


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


# =========================================================
# OpenAI
# =========================================================
def get_openai_client() -> Tuple[Optional["OpenAI"], str, str]:
    api_key = str(st.secrets.get("OPENAI_API_KEY", "")).strip() if hasattr(st, "secrets") else ""
    model = str(st.secrets.get("OPENAI_MODEL", "gpt-4.1-mini")).strip() if hasattr(st, "secrets") else "gpt-4.1-mini"

    # httpx header UnicodeEncodeError 방지: key에 비ASCII(숨은 문자/스마트따옴표 등) 들어가면 바로 에러
    if any(ord(ch) > 127 for ch in api_key):
        return None, model, "OPENAI_API_KEY에 비ASCII(숨은 문자)가 포함되어 있습니다. Streamlit Secrets에서 키를 다시 붙여넣어 주세요."

    if not api_key or OpenAI is None:
        return None, model, "OpenAI 라이브러리 또는 API 키가 없습니다."
    return OpenAI(api_key=api_key), model, ""


def call_openai_text(prompt: str) -> str:
    client, model, err = get_openai_client()
    if client is None:
        return "(테스트 모드) OpenAI 호출 불가.\n\n" + err + "\n\n" + prompt[:1800]

    resp = client.responses.create(model=model, input=prompt)
    return resp.output_text


# =========================================================
# Platform Profiles
# =========================================================
def platform_profile(platform_label: str) -> str:
    if platform_label.startswith("네이버"):
        return """
[네이버 최적화]
- 공감→경험→해결→추천 흐름으로 체류시간을 올린다.
- 문단은 2~4문장, 리듬감 있게.
- 키워드는 억지 반복 금지. 자연스럽게 분산.
"""
    if platform_label.startswith("티스토리"):
        return """
[티스토리(다음/카카오) 최적화]
- 소제목으로 흐름을 정리하되, 본문은 문장형 서사로.
- ‘문제→해결→추천’이 읽히게.
- 키워드는 자연스럽게 분산(남발 금지).
"""
    return """
[블로거(구글) 최적화]
- E-E-A-T: 대표의 현장 관찰/경험/고객 반응을 근거로.
- 소제목은 명확히, 본문은 문장형으로.
- 동의어/연관어로 자연 확장(반복 남발 금지).
"""


# =========================================================
# Prompts
# =========================================================
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

    reviews_rule = (
        "후기 텍스트를 과장 없이 요약하되, 실제 반응 중심으로 문장형 6~10줄로 정리하라."
        if reviews_text.strip()
        else "후기 텍스트가 비어 있으면 ‘고객 후기 반응 요약’ 섹션을 절대 쓰지 마라."
    )

    return f"""
너는 20년차 여성의류 쇼핑몰 미샵(MISHARP) 대표이며,
4050 여성 고객을 매일 상담해온 현장형 MD다.
이 글은 ‘블로그에서 그대로 발행 가능한 원고’다.

{platform_profile(platform)}

[절대 규칙]
1) 첫 문장은 반드시 아래 그대로 시작:
안녕하세요^^ 일상도 스타일도 미샵처럼 심플하게! 20년차 여성의류 쇼핑몰 미샵 대표입니다.
2) 두 번째 문장은 반드시 계절/날씨/시기 공감 + 옷장 앞 고민을 넣어라.
3) 말투: 존댓말 기본. 대중적/캐주얼. 때로 쇼핑호스트, 때로 동네 옷가게 사장님 톤.
4) 구분선(---, ===) 금지. 문단 연결 문장으로 자연스럽게 이어라.
5) 콜론 표기: “단어: 값” 한 칸 띄어쓰기.
6) 분량: 4,000~5,000자 내외(너무 짧게 쓰지 말 것).
7) 마지막 줄: “일상도 스타일도 미샵처럼, 심플하게! MISHARP”
8) 해시태그 30개는 맨 끝 한 줄.

[문장형 규칙(중요)]
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
12) 아이템 사이즈 스펙 표(표는 ‘항목/값’ 형태로 만들기)
13) 사이즈 추천 표(표는 ‘기준/신장·체중/평소 상의/추천 사이즈/코멘트’ 형태로 만들기)
14) 최하단 요약 3줄(문장형)
15) 인용박스(>) CTA 2~3줄
16) 슬로건 + 해시태그 30개(한 줄)

[표 출력 규칙(중요)]
- 표 2개는 반드시 아래 형식 그대로 출력(HTML 변환에 최적화):
  표1)
  [사이즈 스펙]
  | 항목 | 값 |
  |---|---|
  | 어깨단면 | 50 cm |
  표2)
  [사이즈 추천]
  | 기준 | 신장/체중 | 평소 상의 | 추천 사이즈 | 코멘트 |
  |---|---|---|---|---|

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
- 주제관련 일상적 공감 문제 제기/공감 유도
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
# Markdown -> HTML (Naver-friendly)
# - Naver does NOT understand markdown tables when pasted.
# - We convert markdown tables into <table> ... </table>
# - And provide a COPY button that copies HTML to clipboard
# =========================================================
def md_to_html_for_naver(md_text: str) -> str:
    """
    Minimal markdown to HTML converter tailored for Naver paste:
    - headings (#, ##, ###)
    - paragraphs
    - blockquotes (>)
    - markdown tables -> HTML <table>
    - line breaks preserved reasonably
    """
    md_text = (md_text or "").strip()
    md_text = md_text.replace("\r\n", "\n")

    lines = md_text.split("\n")
    html_parts = []

    def esc(x: str) -> str:
        return html.escape(x, quote=False)

    in_table = False
    table_rows = []

    def flush_table():
        nonlocal in_table, table_rows
        if not in_table or not table_rows:
            in_table = False
            table_rows = []
            return
        # First row is header if it looks like header row + separator exists earlier in parsing;
        # We parse more simply: if first row exists -> treat as header
        header = table_rows[0]
        body = table_rows[1:] if len(table_rows) > 1 else []
        # build
        html_parts.append("<table style='border-collapse:collapse; width:100%; margin:10px 0; font-size:14px;'>")
        html_parts.append("<thead><tr>")
        for c in header:
            html_parts.append(
                f"<th style='border:1px solid #ddd; padding:10px; background:#f6f6f6; text-align:left;'>{esc(c)}</th>"
            )
        html_parts.append("</tr></thead>")
        html_parts.append("<tbody>")
        for r in body:
            html_parts.append("<tr>")
            for c in r:
                html_parts.append(
                    f"<td style='border:1px solid #ddd; padding:10px; vertical-align:top;'>{esc(c)}</td>"
                )
            html_parts.append("</tr>")
        html_parts.append("</tbody></table>")
        in_table = False
        table_rows = []

    for ln in lines:
        s = ln.strip()

        # Table separator row like |---|---|
        if re.match(r"^\|\s*[-: ]+\|\s*[-:| ]+\|?$", s):
            # skip separator row
            continue

        # Table row: | a | b |
        if s.startswith("|") and "|" in s[1:]:
            cells = [c.strip() for c in s.strip("|").split("|")]
            # start table if needed
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(cells)
            continue

        # if we were in table and line is not a table row -> flush
        if in_table and not (s.startswith("|") and "|" in s[1:]):
            flush_table()

        if not s:
            html_parts.append("<br/>")
            continue

        # Headings
        if s.startswith("### "):
            html_parts.append(f"<h3 style='margin:16px 0 8px; font-size:18px;'>{esc(s[4:])}</h3>")
            continue
        if s.startswith("## "):
            html_parts.append(f"<h2 style='margin:18px 0 10px; font-size:20px;'>{esc(s[3:])}</h2>")
            continue
        if s.startswith("# "):
            html_parts.append(f"<h1 style='margin:18px 0 12px; font-size:22px;'>{esc(s[2:])}</h1>")
            continue

        # Blockquote
        if s.startswith(">"):
            quote = s[1:].strip()
            html_parts.append(
                f"<blockquote style='margin:12px 0; padding:10px 12px; border-left:4px solid #ddd; background:#fafafa;'>{esc(quote)}</blockquote>"
            )
            continue

        # Bullets / lists: keep as <ul>
        if s.startswith("- "):
            # collect consecutive bullet lines
            bullets = [s[2:].strip()]
            # no lookahead easy in this loop; handled roughly by inserting as paragraph list items
            html_parts.append("<ul style='margin:10px 0 10px 18px;'>")
            html_parts.append(f"<li style='margin:6px 0;'>{esc(bullets[0])}</li>")
            html_parts.append("</ul>")
            continue

        # Normal paragraph
        html_parts.append(f"<p style='margin:10px 0; line-height:1.7;'>{esc(ln)}</p>")

    if in_table:
        flush_table()

    # Remove excessive <br/> sequences
    out = "\n".join(html_parts)
    out = re.sub(r"(<br/>\s*){3,}", "<br/><br/>", out)
    return out.strip()


def html_copy_button(html_text: str, button_label: str = "📋 HTML 복사(네이버 표 유지)") -> None:
    """
    Renders a button that copies given HTML to clipboard.
    Uses JS to copy "text/html" first; falls back to plain text.
    """
    safe = html_text.replace("\\", "\\\\").replace("`", "\\`")
    components.html(
        f"""
<div style="display:flex; gap:10px; align-items:center; margin:8px 0 14px;">
  <button id="copyBtn"
    style="
      background:#ff4d4f; color:white; border:none; padding:10px 14px;
      border-radius:10px; font-weight:700; cursor:pointer;
    ">
    {button_label}
  </button>
  <span id="copyMsg" style="color:rgba(255,255,255,0.65); font-size:13px;"></span>
</div>

<script>
  const htmlContent = `{safe}`;
  const btn = document.getElementById("copyBtn");
  const msg = document.getElementById("copyMsg");

  async function copyHtml() {{
    try {{
      // Try to copy as HTML (best for Naver editor)
      const blob = new Blob([htmlContent], {{ type: "text/html" }});
      const data = [new ClipboardItem({{ "text/html": blob }})];
      await navigator.clipboard.write(data);
      msg.textContent = "복사 완료! 네이버 글쓰기에서 그대로 붙여넣기 하세요.";
      msg.style.color = "#7CFC9A";
    }} catch (e) {{
      try {{
        // Fallback: plain text
        await navigator.clipboard.writeText(htmlContent);
        msg.textContent = "복사 완료(텍스트로 복사됨). 네이버에서는 표가 깨질 수 있어요.";
        msg.style.color = "#FFD580";
      }} catch (e2) {{
        msg.textContent = "복사 실패: 브라우저 보안 정책 때문에 막혔습니다. 아래 HTML 박스를 수동으로 복사해주세요.";
        msg.style.color = "#ff8080";
      }}
    }}
  }}

  btn.addEventListener("click", copyHtml);
</script>
""",
        height=80,
    )


# =========================================================
# UI / Style
# =========================================================
st.set_page_config(page_title="미샵 블로그글 생성기", page_icon="📝", layout="wide")

st.markdown(
    """
<style>
  .block-container { padding-top: 1.6rem; padding-bottom: 2.2rem; max-width: 1180px; }
  h1 { font-size: 2.0rem !important; letter-spacing: -0.02em; }
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
    font-weight: 800;
    margin-bottom: 10px;
    letter-spacing: -0.01em;
  }
  .hint {
    color: rgba(255,255,255,0.65);
    font-size: 0.92rem;
    margin-top: -6px;
    margin-bottom: 10px;
  }
  .tiny {
    color: rgba(255,255,255,0.50);
    font-size: 0.80rem;
    line-height: 1.55;
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

st.title("📝 미샵 블로그 콘텐츠 생성기")
st.markdown(
    '<div class="subcap">블로그 선택 → 주제 입력 → 글 생성 → <b>결과(네이버 HTML 복사)</b> → 이미지/발행</div>',
    unsafe_allow_html=True,
)

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
    st.markdown('<div class="tiny">네이버는 “HTML 복사”로 붙여넣어야 표가 유지됩니다.</div>', unsafe_allow_html=True)
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

    size_spec_text = ""
    reviews_text = ""
    if post_type == "미샵 패션 아이템 글":
        with st.expander("추가 입력(선택): 사이즈/후기", expanded=False):
            size_spec_text = st.text_area("사이즈 스펙(표 재료)", height=120)
            reviews_text = st.text_area("후기 텍스트(있으면 붙여넣기)", height=120)

    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="step-title">3) 글 생성</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="hint">생성 후 5)에서 <b>네이버용 HTML 복사 버튼</b>을 사용하면 ChatGPT처럼 표가 유지됩니다.</div>',
        unsafe_allow_html=True,
    )

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
                user_notes=(notes or "").strip(),
                product_url=(product_url or "").strip(),
                size_spec_text=(size_spec_text or "").strip(),
                reviews_text=(reviews_text or "").strip(),
            )
        else:
            prompt = build_general_prompt(
                platform=platform,
                topic=topic_text.strip(),
                keywords=keywords,
                notes=(notes or "").strip(),
            )

        raw = call_openai_text(prompt)
        raw = normalize_spaces(raw)

        title_guess, body = split_title_and_body(raw, fallback_title=topic_text.strip())

        # Hashtags
        if post_type == "미샵 패션 아이템 글":
            required = ["#미샵", "#여성의류", "#출근룩", "#데일리룩", "#ootd", "#40대여성의류", "#50대여성의류", "#중년여성패션"]
        else:
            required = []
        tags_line = ensure_hashtags_30(required, keywords)

        # Remove possible trailing hashtag block from model, then add our line
        body = re.sub(r"(#\S+\s*){8,}$", "", body, flags=re.MULTILINE).rstrip()
        full_md = (title_guess + "\n\n" + body).strip() + "\n\n" + tags_line
        full_md = normalize_spaces(full_md)

        # Convert to HTML for Naver
        html_for_naver = md_to_html_for_naver(full_md)

        st.session_state["generated_title"] = title_guess
        st.session_state["generated_md"] = full_md
        st.session_state["generated_html"] = html_for_naver

        st.success("생성 완료! 아래 5)에서 네이버용 HTML 복사 버튼을 사용하세요.")

    st.markdown("</div>", unsafe_allow_html=True)

    # 5) Result (KEY)
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="step-title">5) 결과 / 복사 / 다운로드</div>', unsafe_allow_html=True)

    if "generated_md" not in st.session_state:
        st.info("아직 생성된 글이 없습니다. 위에서 **3) 글 생성하기**를 눌러주세요.")
    else:
        title_guess = st.session_state.get("generated_title", "미샵 블로그 글")
        md_text = st.session_state.get("generated_md", "")
        html_text = st.session_state.get("generated_html", "")

        tabs = st.tabs(["✅ 네이버용 HTML 복사(표 유지)", "미리보기", "원문(마크다운/텍스트)", "다운로드"])

        with tabs[0]:
            st.markdown(
                """
**네이버 블로그는 마크다운 표를 못 읽습니다.**
아래 **HTML 복사 버튼**을 눌러서 네이버 글쓰기 편집창에 그대로 붙여넣으면,
ChatGPT 복사처럼 **표가 살아있는 상태로 붙습니다.**
""".strip()
            )
            html_copy_button(html_text, "📋 네이버용 HTML 복사(표 유지)")
            st.text_area("HTML 소스(수동 복사용)", value=html_text, height=280)

        with tabs[1]:
            st.markdown(md_text)

        with tabs[2]:
            st.text_area("원문(마크다운/텍스트) — 메모/백업용", value=md_text, height=420)

        with tabs[3]:
            fname_base = f"{today_yyyymmdd()}_{safe_slug_10chars(title_guess)}"
            st.download_button(
                "⬇️ TXT 다운로드",
                data=md_text,
                file_name=f"{fname_base}.txt",
                mime="text/plain",
                use_container_width=True,
            )
            st.download_button(
                "⬇️ HTML 다운로드(네이버 표 유지)",
                data=html_text,
                file_name=f"{fname_base}.html",
                mime="text/html",
                use_container_width=True,
            )

    st.markdown("</div>", unsafe_allow_html=True)

    # 6) Image / Publish shortcuts
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="step-title">6) 이미지 생성 / 발행 바로가기</div>', unsafe_allow_html=True)
    st.link_button("🖼️ 미샵 상세페이지 이미지 추출기(자동 ZIP)", "https://misharp-image-crop-v1.streamlit.app/", use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.link_button("Pexels (무료)", "https://www.pexels.com/ko-kr/", use_container_width=True)
    with c2:
        st.link_button("Pixabay (무료)", "https://pixabay.com/ko/", use_container_width=True)

    st.markdown("<br/>", unsafe_allow_html=True)
    b1, b2, b3 = st.columns(3)
    with b1:
        st.link_button("네이버 블로그 로그인", "https://nid.naver.com/nidlogin.login", use_container_width=True)
    with b2:
        st.link_button("티스토리 로그인", "https://www.tistory.com/auth/login", use_container_width=True)
    with b3:
        st.link_button("Blogger 로그인", "https://accounts.google.com/signin/v2/identifier?service=blogger", use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

# Footer (always at bottom, small)
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
