import re
import json
import html
import textwrap
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup

# Optional: OpenAI (works if OPENAI_API_KEY exists in Streamlit Secrets)
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
    # rule: "단어와 ':'는 한칸 띄기" -> "단어: 값" 형태로 보정
    # 예) "키워드:값" -> "키워드: 값"
    s = re.sub(r"([가-힣A-Za-z0-9])\s*:\s*", r"\1: ", s)
    # 과도한 공백 정리
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def safe_slug_10chars(title: str) -> str:
    # 파일명에 넣을 "제목간단요약 10자 이내"
    t = re.sub(r"\s+", "", title)
    t = re.sub(r"[^\w가-힣]", "", t)
    return t[:10] if t else "블로그글"


def keywords_from_csv(csv_text: str) -> List[str]:
    if not csv_text.strip():
        return []
    items = [x.strip() for x in csv_text.split(",")]
    items = [x for x in items if x]
    # 중복 제거(순서 유지)
    seen = set()
    out = []
    for x in items:
        if x.lower() not in seen:
            out.append(x)
            seen.add(x.lower())
    return out


def ensure_30_hashtags(base: List[str], extra: List[str]) -> List[str]:
    seen = set()
    out = []
    for tag in base + extra:
        t = tag.strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t
        key = t.lower()
        if key not in seen:
            out.append(t)
            seen.add(key)
        if len(out) >= 30:
            break
    # 부족하면 보충
    filler = [
        "#겨울코디", "#봄코디", "#간절기코디", "#오피스룩", "#하객룩", "#학교상담룩",
        "#체형커버", "#데일리패션", "#중년코디", "#미시룩", "#심플룩", "#꾸안꾸",
        "#스타일링", "#코디추천", "#여성패션", "#쇼핑몰추천", "#오늘의코디", "#데일리코디",
        "#중년여성", "#40대코디", "#50대코디"
    ]
    for t in filler:
        if len(out) >= 30:
            break
        if t.lower() not in seen:
            out.append(t)
            seen.add(t.lower())
    return out[:30]


def html_wrap(title: str, body_md_like: str) -> str:
    # 아주 가벼운 HTML 래핑(블로그 붙여넣기용)
    # 마크다운 완전 변환은 아니고, 문단/리스트/표가 보기 좋게 들어가도록만 처리
    lines = body_md_like.splitlines()
    html_lines = []
    in_ul = False
    for line in lines:
        l = line.rstrip()
        if l.startswith("|") and l.endswith("|"):
            # 표는 별도 처리: md table 그대로 두면 블로그에서 깨질 수 있어 HTML 테이블로 변환 시도
            # 간단 변환: 표 블록을 모아서 pandas로 변환
            # 여기서는 보수적으로 pre 처리
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<pre>{html.escape(l)}</pre>")
            continue

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
        elif re.match(r"^#{1,6}\s+", l):
            level = len(l.split(" ")[0])
            txt = l[level+1:].strip()
            level = min(max(level, 2), 4)  # h2~h4 정도로 제한
            html_lines.append(f"<h{level}>{html.escape(txt)}</h{level}>")
        elif l.startswith(">"):
            html_lines.append(f"<blockquote>{html.escape(l[1:].strip())}</blockquote>")
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


@dataclass
class ProductInfo:
    name: str = ""
    price: str = ""
    url: str = ""
    description_hint: str = ""
    size_spec: Optional[pd.DataFrame] = None
    reviews_hint: str = ""


def try_fetch_misharp_product(url: str, timeout: int = 10) -> ProductInfo:
    """
    미샵 상세 URL이 들어오면 가능한 범위에서 상품명 정도만 자동 추출 시도.
    (사이트 구조/차단/로딩 방식에 따라 실패할 수 있으니, 실패해도 앱은 정상 동작)
    """
    info = ProductInfo(url=url)
    if not url.strip():
        return info
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # 1) title 기반 상품명 힌트
        title = (soup.title.get_text(strip=True) if soup.title else "").strip()
        if title:
            # 흔한 패턴 정리
            title = re.sub(r"\s*-\s*미샵.*$", "", title).strip()
            info.name = title[:60]

        # 2) og:title 우선
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            info.name = og["content"].strip()[:60]

        # 3) 가격(있으면)
        # 사이트마다 다름 -> 숫자/원 패턴 검색(첫 매칭)
        text = soup.get_text(" ", strip=True)
        m = re.search(r"(\d{1,3}(?:,\d{3})+)\s*원", text)
        if m:
            info.price = m.group(1) + "원"

        # 4) 설명 힌트(너무 길면 요약용으로만)
        # 상품 상세 텍스트 일부
        info.description_hint = text[:800]

    except Exception:
        # 실패해도 그냥 빈 값 유지
        pass
    return info


def build_misharp_prompt(
    platform: str,
    product_name: str,
    primary_kw: str,
    keywords: List[str],
    user_notes: str,
    product_url: str,
    size_spec_text: str,
    reviews_text: str
) -> str:
    # 지침 그대로를 시스템급 프롬프트로 강하게 고정
    # (미샵 글 구조/문장 시작/인사말 첫문장/문단 연결/요약/CTA/표/해시태그/슬로건 등)
    kws_joined = ", ".join(keywords) if keywords else ""
    return f"""
너는 20년차 여성의류 쇼핑몰 CEO(미샵 대표)이며, 네이버/다음/구글 SEO에 강한 블로그 작가다.
플랫폼: {platform}
목표: [미샵] + 여성의류 검색에서 상위노출을 노리는 5,000자 내외 블로그 글.

[절대 규칙]
- 첫 문장은 반드시 아래 그대로 시작:
"안녕하세요^^ 일상도 스타일도 미샵처럼 심플하게! 20년차 여성의류 쇼핑몰 미샵 대표입니다."
- 그 다음 문장에는 '시즌/날씨/시기' 인사말을 자연스럽게 추가.
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
4) (자연스러운 타이틀) 디자인/핏이 주는 이점: 체형커버, 날씬해 보임 등
5) (자연스러운 타이틀) 소재/착용감이 주는 생활 속 이점: 구김, 편안함 등
6) (자연스러운 타이틀) 가격/가치 베네핏: 퀄리티 대비 합리적
7) 고객 후기 반응 요약: 후기 텍스트가 비어 있으면 이 문단은 아예 쓰지 말 것
8) 활용성 및 코디 제안(TPO 연결)
9) (자연스러운 타이틀) 이 아이템, 꼭 만나보세요(공감 CTA)
10) 아이템 사이즈 스펙 표(표 형태)
11) 사이즈 추천 표(체형별 추천)
12) 최하단 [요약] 3줄
13) 요약 다음 줄에 인용박스(>)로 필요성 공감 CTA
14) 마지막 줄: "일상도 스타일도 미샵처럼, 심플하게! MISHARP"
15) 해시태그 30개(필수 포함)

[입력 정보]
- 상품명: {product_name}
- 상품 URL: {product_url}
- 핵심 키워드(우선순위): {kws_joined}
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
- 마지막 인사: "오늘 정보가 도움이 되었으면 합니다." 느낌의 창작 인사말

[출력]
- 제목 1개
- 본문
- 해시태그 30개(한 줄)
""".strip()


def call_openai(prompt: str) -> str:
    api_key = st.secrets.get("OPENAI_API_KEY", "").strip() if hasattr(st, "secrets") else ""
    model = st.secrets.get("OPENAI_MODEL", "gpt-5").strip() if hasattr(st, "secrets") else "gpt-5"

    if not api_key or OpenAI is None:
        # Fallback: 규칙 기반 “임시 글” (테스트용)
        return "(테스트 모드) OpenAI 키가 없어 규칙 기반 임시 글을 출력합니다.\n\n" + prompt[:1800]

    client = OpenAI(api_key=api_key)
    # Responses API 기본 사용 예시는 OpenAI 공식 Quickstart를 따름
    resp = client.responses.create(
        model=model,
        input=prompt
    )
    return resp.output_text


def build_size_tables_default() -> Tuple[pd.DataFrame, pd.DataFrame]:
    spec = pd.DataFrame(
        [
            {"사이즈": "FREE", "어깨": "-", "가슴": "-", "암홀": "-", "소매": "-", "총장": "-"},
            {"사이즈": "S", "어깨": "-", "가슴": "-", "암홀": "-", "소매": "-", "총장": "-"},
            {"사이즈": "M", "어깨": "-", "가슴": "-", "암홀": "-", "소매": "-", "총장": "-"},
            {"사이즈": "L", "어깨": "-", "가슴": "-", "암홀": "-", "소매": "-", "총장": "-"},
        ]
    )
    rec = pd.DataFrame(
        [
            {"체형": "55", "추천": "S 또는 FREE(슬림/정핏 선호 기준)", "코멘트": "상체 슬림, 단정핏 추천"},
            {"체형": "66", "추천": "M 또는 FREE", "코멘트": "군살 커버 + 편안함 밸런스"},
            {"체형": "66반~77", "추천": "L 또는 여유핏", "코멘트": "상체/복부 여유 있게"},
        ]
    )
    return spec, rec


# =========================
# UI
# =========================
st.set_page_config(
    page_title="미샵 블로그 콘텐츠 생성기",
    page_icon="📝",
    layout="wide"
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.2rem; padding-bottom: 2.5rem; }
      .step-card {
        border: 1px solid rgba(0,0,0,0.08);
        border-radius: 16px;
        padding: 16px 18px;
        background: white;
      }
      .muted { color: rgba(0,0,0,0.55); font-size: 0.92rem; }
      .pill {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(0,0,0,0.05);
        margin-right: 6px;
        font-size: 0.86rem;
      }
      .big-title { font-size: 1.35rem; font-weight: 800; margin-bottom: 0.25rem; }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown('<div class="big-title">📝 미샵 블로그 콘텐츠 생성기</div>', unsafe_allow_html=True)
st.markdown('<div class="muted">블로그 선택 → 주제/URL 입력 → 글 생성(TXT/HTML/복사) → 이미지/발행 → 카피라이트</div>', unsafe_allow_html=True)

left, right = st.columns([1.0, 1.05], gap="large")

with left:
    st.markdown('<div class="step-card">', unsafe_allow_html=True)
    st.markdown("### 1) 블로그 선택")
    platform = st.radio(
        "플랫폼",
        ["네이버(네이버 SEO)", "티스토리(다음/카카오 SEO)", "블로거(구글 SEO)"],
        horizontal=True
    )
    platform_key = "naver" if platform.startswith("네이버") else ("tistory" if platform.startswith("티스토리") else "blogger")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="step-card" style="margin-top:12px;">', unsafe_allow_html=True)
    st.markdown("### 2) 주제 입력")
    post_type = st.selectbox("글 유형", ["미샵 패션 아이템 글", "기타 주제 글"])

    colA, colB = st.columns([1, 1], gap="small")
    with colA:
        product_url = st.text_input("상품 URL (선택)", placeholder="https://misharp.co.kr/product/detail.html?product_no=...")
    with colB:
        topic_text = st.text_input("주제/상품명 (필수)", placeholder="예) 소울 하이넥 반목 니트 / 40대 출근룩 코디")

    kw_csv = st.text_input("키워드 (','로 구분)", placeholder="예) 40대여성의류, 50대여성의류, 출근룩, 데일리룩, 체형커버")
    keywords = keywords_from_csv(kw_csv)

    notes = st.text_area(
        "내용 입력 (글자수 제한 없음 / 상세설명/원고/메모 붙여넣기)",
        height=220,
        placeholder="여기에 미샵 상세페이지 원고, 소재/핏/추천상황, 고객 FAQ 등 원하는 재료를 넣어주세요."
    )
    st.caption("TIP) 상품 URL 자동 추출이 실패할 수 있으니, 중요한 내용은 위 입력칸에 붙여넣는 방식이 가장 안전합니다.")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="step-card" style="margin-top:12px;">', unsafe_allow_html=True)
    st.markdown("### 3) (선택) 사이즈/후기 입력")
    st.caption("후기 없으면 '후기 요약 문단'은 자동으로 제외되게 프롬프트 규칙에 포함돼 있습니다.")
    size_spec_text = st.text_area("사이즈 스펙 (표로 만들 재료)", height=130, placeholder="예) 어깨단면 38 / 가슴둘레 100 / 총장 60 ...")
    reviews_text = st.text_area("후기 텍스트 (있으면 붙여넣기)", height=130, placeholder="후기 여러 개를 붙여넣으면 요약해줍니다. 없으면 비워두세요.")
    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="step-card">', unsafe_allow_html=True)
    st.markdown("### 4) 글 생성")
    st.markdown(
        f"""
        <span class="pill">플랫폼: {platform}</span>
        <span class="pill">유형: {post_type}</span>
        <span class="pill">날짜: {today_yyyymmdd()}</span>
        """,
        unsafe_allow_html=True
    )

    fetch_btn = st.button("🔎 (선택) URL에서 상품명 자동 추출", use_container_width=True)
    if fetch_btn and product_url.strip():
        info = try_fetch_misharp_product(product_url.strip())
        if info.name:
            st.success(f"추출된 상품명: {info.name}")
            if not topic_text.strip():
                st.session_state["topic_autofill"] = info.name
        else:
            st.warning("자동 추출이 실패했어요. 주제/상품명 입력칸에 직접 적어주시는 게 가장 안전합니다.")

    # Autofill
    if "topic_autofill" in st.session_state and not topic_text.strip():
        topic_text = st.session_state["topic_autofill"]

    generate_btn = st.button("✨ 글 생성하기", type="primary", use_container_width=True)

    if generate_btn:
        if not topic_text.strip():
            st.error("주제/상품명(필수)을 입력해주세요.")
        else:
            with st.spinner("글 생성 중..."):
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
                        notes=notes.strip()
                    )

                out_text = call_openai(prompt)
                out_text = normalize_spaces(out_text)

                # 해시태그 보정: 반드시 30개 & 필수 포함(미샵 글일 때)
                if post_type == "미샵 패션 아이템 글":
                    required = ["#미샵", "#여성의류", "#출근룩", "#데일리룩", "#ootd", "#40대여성의류", "#50대여성의류", "#중년여성패션"]
                else:
                    required = []

                # 본문에 해시태그가 있든 없든, 마지막에 30개 한 줄로 확정 출력
                extra = []
                # 키워드 기반 태그 추가
                for k in keywords[:25]:
                    extra.append("#" + re.sub(r"\s+", "", k))
                tags = ensure_30_hashtags(required, extra)

                # 본문 끝에 이미 태그가 있으면 중복될 수 있으니, "마지막 해시태그 줄"을 강제 교체
                out_text_wo_tags = re.sub(r"(#\S+\s*){8,}$", "", out_text, flags=re.MULTILINE).rstrip()
                out_text = out_text_wo_tags + "\n\n" + " ".join(tags)

                # 카피라이트 고지(한글/영문) + 슬로건은 미샵 글은 본문 규칙에도 포함되어 있으나, 하단 별도 표시도 제공
                copyright_kr = "ⓒ 미샵컴퍼니(MISHARP COMPANY). 본 콘텐츠의 저작권은 미샵컴퍼니에 있으며, 무단 복제·배포·전재·2차 가공 및 상업적 이용을 금합니다."
                copyright_en = "ⓒ MISHARP COMPANY. All rights reserved. Unauthorized copying, redistribution, republication, modification, or commercial use is strictly prohibited."

                st.session_state["generated_text"] = out_text
                st.session_state["generated_title"] = out_text.splitlines()[0].strip() if out_text.splitlines() else topic_text.strip()
                st.session_state["copyright_kr"] = copyright_kr
                st.session_state["copyright_en"] = copyright_en

            st.success("생성 완료! 아래에서 TXT/HTML/복사로 사용하세요.")

    if "generated_text" in st.session_state:
        title_guess = st.session_state.get("generated_title", topic_text.strip())
        content_text = st.session_state["generated_text"]

        st.markdown("#### ✅ 결과 (텍스트)")
        st.text_area("생성된 글 (여기서 전체 선택 후 복사 가능)", value=content_text, height=360)

        st.markdown("#### ✅ HTML 소스")
        html_doc = html_wrap(title_guess, content_text)
        st.code(html_doc, language="html")

        # TXT 다운로드(파일명: 날짜+제목요약10자)
        fname = f"{today_yyyymmdd()}_{safe_slug_10chars(title_guess)}.txt"
        st.download_button(
            "⬇️ TXT 다운로드",
            data=(content_text + "\n\n" + st.session_state["copyright_kr"] + "\n" + st.session_state["copyright_en"]),
            file_name=fname,
            mime="text/plain",
            use_container_width=True
        )

        # HTML 다운로드
        fname_html = f"{today_yyyymmdd()}_{safe_slug_10chars(title_guess)}.html"
        st.download_button(
            "⬇️ HTML 다운로드",
            data=html_doc,
            file_name=fname_html,
            mime="text/html",
            use_container_width=True
        )

        st.markdown("#### 5) 카피라이트 고지 (한글/영문)")
        st.write(st.session_state["copyright_kr"])
        st.write(st.session_state["copyright_en"])

    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="step-card" style="margin-top:12px;">', unsafe_allow_html=True)
    st.markdown("### 6) 이미지 생성 / 발행 바로가기")

    st.markdown("**미샵 상세페이지 이미지 추출기(자동 ZIP 생성):**")
    st.link_button("🖼️ misharp-image-crop-v1 열기", "https://misharp-image-crop-v1.streamlit.app/", use_container_width=True)

    st.markdown("**저작권 걱정 없는 이미지 소스:**")
    c1, c2 = st.columns(2)
    with c1:
        st.link_button("Pexels (무료)", "https://www.pexels.com/ko-kr/", use_container_width=True)
    with c2:
        st.link_button("Pixabay (무료)", "https://pixabay.com/ko/", use_container_width=True)

    st.markdown("**발행 로그인 링크:**")
    b1, b2, b3 = st.columns(3)
    with b1:
        st.link_button("네이버 블로그 로그인", "https://nid.naver.com/nidlogin.login", use_container_width=True)
    with b2:
        st.link_button("티스토리 로그인", "https://www.tistory.com/auth/login", use_container_width=True)
    with b3:
        st.link_button("Blogger 로그인", "https://accounts.google.com/signin/v2/identifier?service=blogger", use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

st.caption("※ 이 앱은 형준님이 정리한 제작 지침을 그대로 반영해, 오류가 나도 '통째로 교체' 방식으로 즉시 수정 가능하도록 단일 app.py 중심으로 구성했습니다.")
