import re
import html
from datetime import datetime
from typing import List

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


# =========================
# OpenAI
# =========================
def call_openai(prompt: str) -> str:
    api_key = ""
    model = "gpt-5"

    if hasattr(st, "secrets"):
        api_key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        model = str(st.secrets.get("OPENAI_MODEL", "gpt-5")).strip()

    if not api_key or OpenAI is None:
        return "(테스트 모드) OpenAI 키가 없어 규칙 기반 임시 출력입니다.\n\n" + prompt[:1800]

    client = OpenAI(api_key=api_key)
    resp = client.responses.create(model=model, input=prompt)
    return resp.output_text


# =========================
# Prompts
# =========================
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
    return f"""
너는 20년차 여성의류 쇼핑몰 CEO(미샵 대표)이며, 네이버/다음/구글 SEO에 강한 블로그 작가다.
플랫폼: {platform}
목표: [미샵] + 여성의류 검색에서 상위노출을 노리는 5,000자 내외 블로그 글.

[절대 규칙]
- 첫 문장은 반드시 아래 그대로 시작:
"안녕하세요^^ 일상도 스타일도 미샵처럼 심플하게! 20년차 여성의류 쇼핑몰 미샵 대표입니다."
- 그 다음 문장에는 시즌/날씨/시기 인사말을 자연스럽게 추가.
- 각 문단의 시작은 반드시 "미샵 {product_name}은(는) " 으로 시작.
- 문단 사이 구분선(--- 등) 금지. 대신 공감 유도 연결문장으로 자연스럽게 이어가라.
- 콜론 표기 시 "단어: 값"으로 한 칸 띄어쓰기.
- 제목에는 반드시 "[미샵]" 포함, 상위 키워드 1개 포함("{primary_kw}"), 카테고리 키워드로 SEO 최적화.
- 말투: 대중적/캐주얼, 때로는 쇼핑호스트 톤, 때로는 오프라인 옷가게 사장님 톤.
- 해시태그는 맨 끝에 30개를 한 줄로.

[필수 문단 구성(순서 유지)]
1) 최상단 요약(3~5줄)
2) 이런 분들께 추천합니다(4050 체형/TPO) - 리스팅
3) 이럴 때 요긴해요 - 상황 리스팅
4) (자연스러운 타이틀) 디자인/핏이 주는 이점
5) (자연스러운 타이틀) 소재/착용감이 주는 생활 속 이점
6) (자연스러운 타이틀) 가격/가치 베네핏
7) 고객 후기 반응 요약: 후기 텍스트가 비어 있으면 이 문단은 아예 쓰지 말 것
8) 활용성 및 코디 제안(TPO 연결)
9) (자연스러운 타이틀) 이 아이템, 꼭 만나보세요(공감 CTA)
10) 아이템 사이즈 스펙 표
11) 사이즈 추천 표(체형별)
12) 최하단 [요약] 3줄
13) 요약 다음 줄에 인용박스(>) CTA
14) 마지막 줄: "일상도 스타일도 미샵처럼, 심플하게! MISHARP"
15) 해시태그 30개(필수 포함)

[입력 정보]
- 상품명: {product_name}
- 상품 URL: {product_url}
- 핵심 키워드: {kws_joined}
- 사용자 추가 메모/원고:
{user_notes}

- 사이즈 스펙(사용자 제공):
{size_spec_text}

- 후기(사용자 제공):
{reviews_text}

[출력]
- 제목 1개
- 본문(위 구조)
- 맨 끝 해시태그 30개(한 줄)
""".strip()


def build_general_prompt(platform: str, topic: str, keywords: List[str], notes: str) -> str:
    kws_joined = ", ".join(keywords) if keywords else ""
    return f"""
너는 {platform} SEO에 최적화된 블로그 글을 쓰는 전문가다.
분량: 약 5,000자.
키워드: {kws_joined} (본문에 과하지 않게 자연스럽게 분산)

[글 시작 고정]
"안녕하세요, 000입니다. (시기적으로 적절한 인삿말) 오늘은 ({topic})에 대해 얘기해볼까해요."

[필수 구성]
- 최상단 글요약(3~5줄)
- 일상적 공감 문제 제기/공감 유도
- 본문(문단별 소제목으로 구조화)
- 마지막 요약(3줄)
- 해시태그 30개(한 줄)
- 마지막 인사(창작): 오늘 정보가 도움이 되었으면 한다는 의미

[입력 메모]
{notes}

[출력]
- 제목 1개
- 본문
- 해시태그 30개(한 줄)
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
            topic_text = st.text_input("주제/상품명 (필수)", placeholder="예) 소울 하이넥 반목 니트 / 40대 출근룩 코디")

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

            out_text = call_openai(prompt)
            out_text = normalize_spaces(out_text)

            # 해시태그 30개 보정
            if post_type == "미샵 패션 아이템 글":
                required = ["#미샵", "#여성의류", "#출근룩", "#데일리룩", "#ootd", "#40대여성의류", "#50대여성의류", "#중년여성패션"]
            else:
                required = []

            extra = ["#" + re.sub(r"\s+", "", k) for k in keywords[:25]]
            tags = ensure_30_hashtags(required, extra)

            # 기존 해시태그 덩어리 제거 후 재부착
            out_text = re.sub(r"(#\S+\s*){8,}$", "", out_text, flags=re.MULTILINE).rstrip()
            out_text = out_text + "\n\n" + " ".join(tags)

            title_guess = out_text.splitlines()[0].strip() if out_text.splitlines() else topic_text.strip()

            st.session_state["generated_text"] = out_text
            st.session_state["generated_title"] = title_guess
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

            st.text_area("본문(전체 선택 → 복사)", value=content_text, height=280)

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
