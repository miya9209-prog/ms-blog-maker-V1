import re
import html
from datetime import datetime
from typing import List, Tuple

import streamlit as st

# Optional: OpenAI
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# =========================
# Helpers
# =========================
def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def normalize_spaces(s: str) -> str:
    # "단어: 값" 콜론 한칸 띄우기
    s = re.sub(r"([가-힣A-Za-z0-9])\s*:\s*", r"\1: ", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def safe_slug_10chars(title: str) -> str:
    t = re.sub(r"\s+", "", title)
    t = re.sub(r"[^\w가-힣]", "", t)
    return t[:10] if t else "블로그글"


def keywords_from_csv(csv_text: str) -> List[str]:
    if not csv_text.strip():
        return []
    items = [x.strip() for x in csv_text.split(",")]
    items = [x for x in items if x]
    seen = set()
    out = []
    for x in items:
        k = x.lower()
        if k not in seen:
            out.append(x)
            seen.add(k)
    return out


def ensure_30_hashtags(base: List[str], extra: List[str]) -> List[str]:
    seen = set()
    out = []

    def add(tag: str):
        nonlocal out
        t = tag.strip()
        if not t:
            return
        if not t.startswith("#"):
            t = "#" + t
        k = t.lower()
        if k in seen:
            return
        out.append(t)
        seen.add(k)

    for t in base:
        add(t)
    for t in extra:
        add(t)
        if len(out) >= 30:
            return out[:30]

    filler = [
        "#겨울코디", "#봄코디", "#간절기코디", "#오피스룩", "#하객룩", "#학교상담룩",
        "#체형커버", "#데일리패션", "#중년코디", "#미시룩", "#심플룩", "#꾸안꾸",
        "#스타일링", "#코디추천", "#여성패션", "#쇼핑몰추천", "#오늘의코디", "#데일리코디",
        "#중년여성", "#40대코디", "#50대코디"
    ]
    for t in filler:
        add(t)
        if len(out) >= 30:
            break
    return out[:30]


def html_wrap(title: str, body_text: str) -> str:
    # 간단 HTML 래핑 (블로그 붙여넣기용)
    lines = body_text.splitlines()
    html_lines = []
    in_ul = False

    for line in lines:
        l = line.rstrip()

        # 리스트(- 또는 •)
        if re.match(r"^\s*[-•]\s+", l):
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            item = re.sub(r"^\s*[-•]\s+", "", l)
            html_lines.append(f"<li>{html.escape(item)}</li>")
            continue
        else:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False

        if l.strip() == "":
            html_lines.append("<br/>")
        else:
            # 소제목처럼 보이는 라인 처리(짧고 끝이 '요', '다' 아닌 경우)
            if len(l) <= 34 and not l.endswith(("요", "다", ".", "!", "?", ")")):
                html_lines.append(f"<h3>{html.escape(l)}</h3>")
            else:
                html_lines.append(f"<p>{html.escape(l)}</p>")

    if in_ul:
        html_lines.append("</ul>")

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
</head>
<body>
{''.join(html_lines)}
</body>
</html>
"""


def strip_title_prefix(line: str) -> str:
    l = line.strip()
    l = re.sub(r"^(제목\s*[:：]\s*)", "", l)
    l = re.sub(r"^(\[제목\]\s*)", "", l)
    l = re.sub(r"^(TITLE\s*[:：]\s*)", "", l, flags=re.IGNORECASE)
    return l.strip()


def split_title_and_body(generated: str, fallback_title: str) -> Tuple[str, str]:
    txt = generated.strip()
    if not txt:
        return fallback_title, ""

    lines = txt.splitlines()
    # 첫 유효 라인을 제목으로
    title_line_idx = None
    for i, ln in enumerate(lines):
        if ln.strip():
            title_line_idx = i
            break
    if title_line_idx is None:
        return fallback_title, txt

    title = strip_title_prefix(lines[title_line_idx])
    # 너무 길면 fallback
    if len(title) > 80 or len(title) < 4:
        title = fallback_title

    body = "\n".join(lines[title_line_idx + 1:]).strip()
    return title, body


# =========================
# OpenAI
# =========================
def call_openai(prompt: str) -> str:
    api_key = ""
    model = "gpt-4.1-mini"

    if hasattr(st, "secrets"):
        api_key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        model = str(st.secrets.get("OPENAI_MODEL", "gpt-4.1-mini")).strip()

    if not api_key or OpenAI is None:
        # 테스트 모드(키 없을 때)
        return "(테스트 모드) OpenAI 키가 없어 규칙 기반 임시 출력입니다.\n\n" + prompt[:1800]

    client = OpenAI(api_key=api_key)
    resp = client.responses.create(model=model, input=prompt)
    return resp.output_text


# =========================
# Prompts
# =========================
def platform_profile(platform_label: str) -> str:
    # 플랫폼별 미세 SEO/서술 가이드
    if platform_label.startswith("네이버"):
        return """
[네이버 최적화]
- 초반 5~8줄 안에 핵심 키워드 1회 자연 삽입(억지 금지)
- 문단은 짧게(2~4문장), ‘대화하듯’ 리듬감 있게
- 공감/상황/경험형 표현을 늘려 체류시간을 올려라
- 과한 마크다운/표 과다 금지(표는 2개만: 사이즈스펙, 사이즈추천)
"""
    if platform_label.startswith("티스토리"):
        return """
[티스토리(다음/카카오) 최적화]
- 소제목(짧은 문장형)으로 흐름을 분절해 가독성 강화
- '문제→해결→추천' 흐름을 명확히
- 키워드는 과하지 않게 8~12회 분산(자연 문맥)
- 표는 2개만, 나머지는 설명을 ‘생활 맥락’으로 풀어라
"""
    return """
[블로거(구글) 최적화]
- H2/H3 느낌의 소제목을 명확히(짧고 정보성)
- E-E-A-T: 20년차 대표의 관찰/고객 반응/현장 경험을 근거로
- 반복 키워드보다, 다양한 관련 표현(동의어/연관어)로 자연 확장
- 요약/정리/체크리스트 스타일을 섞어 ‘정보글’ 품질 확보
"""


def build_misharp_prompt(
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

    # 후기 없으면 문단 생략 강하게 지시
    reviews_rule = "후기 텍스트가 비어 있으면 '고객 후기 반응 요약' 섹션을 절대 쓰지 마라."
    if reviews_text.strip():
        reviews_rule = "후기 텍스트를 요약하되, 과장하지 말고 핵심 반응만 5~8줄로 정리하라."

    return f"""
너는 20년차 여성의류 쇼핑몰 미샵(MISHARP) 대표이자, 4050 여성 고객을 실제로 상담해온 현장형 MD다.
이 글은 ‘상품 설명서’가 아니라, 4050 여성의 옷 고민을 해결해주는 ‘상담형 블로그 글’이다.

{platform_profile(platform)}

[필수 시작 문장(첫 문장 고정)]
안녕하세요^^ 일상도 스타일도 미샵처럼 심플하게! 20년차 여성의류 쇼핑몰 미샵 대표입니다.

[절대 규칙]
- 두 번째 문장에는 반드시 계절/날씨/시기 인사말 + 옷장 앞 고민 공감을 넣어라.
- 말투: 기본 존댓말. 설명서처럼 딱딱하게 쓰지 말고, 옷가게 사장님/쇼핑호스트 톤을 섞어 ‘대화하듯’ 써라.
- 문단 시작 문장을 반복하지 말라(“미샵 {product_name}은(는)…” 강제 금지).
- 문단과 문단 사이 구분선(---, ====) 금지. 연결 문장으로 자연스럽게 이어라.
- 콜론 표기: “단어: 값”으로 한 칸 띄어쓰기.
- 과장/허위 금지. “고객이 실제로 자주 말하는 표현” 느낌으로만.
- 분량: 4,000~5,000자 내외.
- 마지막 줄: “일상도 스타일도 미샵처럼, 심플하게! MISHARP”
- 해시태그 30개: 맨 끝에 한 줄로.

[SEO 규칙]
- 제목은 30~35자 권장.
- 제목에는 반드시 “[미샵]” 포함, 상위 키워드 1개 포함: {primary_kw}
- 본문에는 “미샵, 여성의류, 40대여성의류, 50대여성의류, 출근룩, 데일리룩”을 억지 없이 자연 삽입.
- 키워드({kws_joined})는 자연스럽게 분산(총 8~12회 정도 느낌), 반복/나열 금지.

[글 구성(유연하지만 순서 유지)]
1) 최상단 요약 3~5줄(‘오늘 이 글에서 얻는 것’)
2) 공감 도입: 생활 장면(출근/모임/상담/계절 변화 등) + “이런 고민 많으시죠?”
3) 이런 분들께 추천합니다(리스팅 5~7개, 4050 체형/TPO 중심)
4) 이럴 때 요긴해요(상황 리스팅 5~7개)
5) 디자인/핏이 주는 이점(생활 맥락 속에서: 상체 작아보임/체형커버/비율 등)
6) 소재/착용감이 주는 생활 속 이점(구김/가벼움/포근함/세탁/움직임 등 ‘하루’ 기준)
7) 가격/가치 베네핏(합리성은 ‘경험 기반’으로 설득)
8) 고객 후기 반응 요약(조건): {reviews_rule}
9) 활용성 및 코디 제안(TPO 연결, 3~5가지 제안)
10) “이 아이템, 꼭 만나보세요” (공감 CTA, 부담 없는 확신)
11) 아이템 사이즈 스펙 표(입력 데이터 기반)
12) 사이즈 추천 표(체형별)
13) 최하단 요약 3줄
14) 인용박스(>)로 CTA 2~3줄
15) 슬로건 + 해시태그 30개(한 줄)

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

[출력 형식(매우 중요)]
- 1행: 제목만 출력(“제목:” 같은 접두어 금지)
- 2행: 빈 줄
- 3행부터: 본문
- 마지막 2~3행: 슬로건 포함
- 맨 마지막 줄: 해시태그 30개를 한 줄로
""".strip()


def build_general_prompt(platform: str, topic: str, keywords: List[str], notes: str) -> str:
    kws_joined = ", ".join(keywords) if keywords else ""
    return f"""
너는 {platform} SEO에 최적화된 블로그 글을 쓰는 전문가다.
분량: 약 4,000~5,000자.
키워드({kws_joined})는 자연스럽게 분산(억지 반복 금지).

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
- 3행부터: 본문
- 맨 마지막 줄: 해시태그 30개 한 줄
""".strip()


# =========================
# UI
# =========================
st.set_page_config(page_title="미샵 블로그 콘텐츠 생성기", page_icon="📝", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 2.0rem; padding-bottom: 2.4rem; }
      h1 { font-size: 2.2rem !important; }
      .misharp-footer {
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
st.caption("블로그 선택 → 주제/URL 입력 → 글 생성(TXT/HTML/복사) → 이미지/발행 (카피라이트는 최하단 고정)")

left, right = st.columns([1.05, 1.0], gap="large")

with left:
    with st.container(border=True):
        st.subheader("1) 블로그 선택")
        platform = st.radio(
            "플랫폼",
            ["네이버(네이버 SEO)", "티스토리(다음/카카오 SEO)", "블로거(구글 SEO)"],
            horizontal=True,
        )

    with st.container(border=True):
        st.subheader("2) 주제 입력")
        post_type = st.selectbox("글 유형", ["미샵 패션 아이템 글", "기타 주제 글"])

        c1, c2 = st.columns([1, 1], gap="small")
        with c1:
            product_url = st.text_input("상품 URL (선택)", placeholder="https://misharp.co.kr/product/detail.html?product_no=...")
        with c2:
            topic_text = st.text_input("주제/상품명 (필수)", placeholder="예) 트루 피치 체크 셔츠 / 40대 출근룩 코디")

        kw_csv = st.text_input("키워드 (','로 구분)", placeholder="예) 40대여성의류, 50대여성의류, 출근룩, 데일리룩, 체형커버")
        keywords = keywords_from_csv(kw_csv)

        notes = st.text_area("내용 입력(상세설명/원고/메모)", height=220)

    with st.container(border=True):
        st.subheader("3) (선택) 사이즈 / 후기 입력")
        size_spec_text = st.text_area("사이즈 스펙(표 재료)", height=120)
        reviews_text = st.text_area("후기 텍스트(있으면 붙여넣기)", height=120)

with right:
    # STEP 4
    with st.container(border=True):
        st.subheader("4) 글 생성")
        st.write(f"플랫폼: **{platform}** · 유형: **{post_type}** · 날짜: **{today_yyyymmdd()}**")

        if st.button("✨ 글 생성하기", type="primary", use_container_width=True):
            if not topic_text.strip():
                st.error("주제/상품명(필수)을 입력해주세요.")
                st.stop()

            primary_kw = keywords[0] if keywords else (topic_text.strip().split()[0] if topic_text.strip() else "여성의류")

            if post_type == "미샵 패션 아이템 글":
                prompt = build_misharp_prompt(
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

            raw = call_openai(prompt)
            raw = normalize_spaces(raw)

            title_guess, body = split_title_and_body(raw, fallback_title=topic_text.strip())

            # 해시태그 30개 보정
            if post_type == "미샵 패션 아이템 글":
                required = ["#미샵", "#여성의류", "#출근룩", "#데일리룩", "#ootd", "#40대여성의류", "#50대여성의류", "#중년여성패션"]
            else:
                required = []

            extra = ["#" + re.sub(r"\s+", "", k) for k in keywords[:25]]
            tags = ensure_30_hashtags(required, extra)

            # 본문 끝에 해시태그가 이미 붙었어도, 마지막 줄은 우리가 만든 것으로 통일
            body = re.sub(r"(#\S+\s*){8,}$", "", body, flags=re.MULTILINE).rstrip()
            full_text = (title_guess + "\n\n" + body).strip() + "\n\n" + " ".join(tags)

            st.session_state["generated_title"] = title_guess
            st.session_state["generated_text"] = full_text
            st.success("생성 완료! 아래 5)에서 복사/다운로드 하세요.")

    # STEP 5 (항상 표시)
    with st.container(border=True):
        st.subheader("5) 결과 / TXT·HTML / 복사")
        if "generated_text" not in st.session_state:
            st.info("아직 생성된 글이 없습니다. 위에서 **4) 글 생성하기**를 눌러주세요.")
        else:
            title_guess = st.session_state.get("generated_title", "미샵 블로그 글")
            content_text = st.session_state["generated_text"]

            st.text_input("제목(자동)", value=title_guess, disabled=True)
            st.text_area("본문(전체 선택 → 복사)", value=content_text, height=320)

            html_doc = html_wrap(title_guess, content_text)
            st.subheader("HTML 소스(블로그 HTML 붙여넣기용)")
            st.code(html_doc, language="html")

            fname = f"{today_yyyymmdd()}_{safe_slug_10chars(title_guess)}.txt"
            st.download_button(
                "⬇️ TXT 다운로드",
                data=content_text,
                file_name=fname,
                mime="text/plain",
                use_container_width=True,
            )

    # STEP 6
    with st.container(border=True):
        st.subheader("6) 이미지 생성 / 발행 바로가기")
        st.link_button("🖼️ misharp-image-crop-v1 열기", "https://misharp-image-crop-v1.streamlit.app/", use_container_width=True)
        c1, c2 = st.columns(2)
        with c1:
            st.link_button("Pexels (무료)", "https://www.pexels.com/ko-kr/", use_container_width=True)
        with c2:
            st.link_button("Pixabay (무료)", "https://pixabay.com/ko/", use_container_width=True)

        b1, b2, b3 = st.columns(3)
        with b1:
            st.link_button("네이버 블로그 로그인", "https://nid.naver.com/nidlogin.login", use_container_width=True)
        with b2:
            st.link_button("티스토리 로그인", "https://www.tistory.com/auth/login", use_container_width=True)
        with b3:
            st.link_button("Blogger 로그인", "https://accounts.google.com/signin/v2/identifier?service=blogger", use_container_width=True)


# Footer: 항상 최하단, 작게
st.markdown(
    """
    <div class="misharp-footer">
        ⓒ 미샵컴퍼니(MISHARP COMPANY). 본 콘텐츠의 저작권은 미샵컴퍼니에 있으며,
        무단 복제·배포·전재·2차 가공 및 상업적 이용을 금합니다.<br/>
        ⓒ MISHARP COMPANY. All rights reserved. Unauthorized copying, redistribution,
        republication, modification, or commercial use is strictly prohibited.
    </div>
    """,
    unsafe_allow_html=True
)
