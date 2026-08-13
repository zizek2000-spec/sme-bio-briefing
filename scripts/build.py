#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
중기부·바이오 데스크 브리핑 빌더
--------------------------------
국내 주요 경제지 RSS를 수집 → 중복 제거 → 중기부/중견·중소/벤처/바이오
키워드로 스코어링 → 단독·취재 감지 → 섹션 분류 → index.html 렌더.

의존성: 파이썬 표준 라이브러리만 사용 (pip 설치 불필요).
실행:   python scripts/build.py
출력:   저장소 루트의 index.html
"""

import html
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "index.html")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# ---------------------------------------------------------------------------
# 1) 소스 (검증된 국내 경제지 RSS)
#    weight = 이 섹션에서 나온 기사에 붙는 기본 가중치
#    kind   = 표시용 섹션 이름
# ---------------------------------------------------------------------------
SOURCES = [
    # 전자신문 — 중기/벤처·바이오 전용 피드 (담당 분야 핵심)
    {"outlet": "전자신문", "kind": "중기·벤처", "weight": 9,
     "url": "http://rss.etnews.com/22069.xml"},
    {"outlet": "전자신문", "kind": "바이오",   "weight": 8,
     "url": "http://rss.etnews.com/20042.xml"},
    {"outlet": "전자신문", "kind": "정책",     "weight": 5,
     "url": "http://rss.etnews.com/22210.xml"},
    {"outlet": "전자신문", "kind": "경제",     "weight": 3,
     "url": "http://rss.etnews.com/02.xml"},
    {"outlet": "전자신문", "kind": "유통",     "weight": 2,
     "url": "http://rss.etnews.com/60068.xml"},

    # 한국경제
    {"outlet": "한국경제", "kind": "경제",     "weight": 4,
     "url": "https://www.hankyung.com/feed/economy"},
    {"outlet": "한국경제", "kind": "바이오·IT", "weight": 5,
     "url": "https://www.hankyung.com/feed/it"},
    {"outlet": "한국경제", "kind": "금융",     "weight": 2,
     "url": "https://www.hankyung.com/feed/finance"},
    {"outlet": "한국경제", "kind": "정치·정책", "weight": 3,
     "url": "https://www.hankyung.com/feed/politics"},

    # 서울경제
    {"outlet": "서울경제", "kind": "기업",     "weight": 4,
     "url": "https://www.sedaily.com/rss/business"},
    {"outlet": "서울경제", "kind": "경제",     "weight": 3,
     "url": "https://www.sedaily.com/rss/economy"},
    {"outlet": "서울경제", "kind": "산업·IT",  "weight": 3,
     "url": "https://www.sedaily.com/rss/market"},

    # 이투데이
    {"outlet": "이투데이", "kind": "산업",     "weight": 3,
     "url": "https://rss.etoday.co.kr/eto/industry_news.xml"},
    {"outlet": "이투데이", "kind": "경제",     "weight": 2,
     "url": "https://rss.etoday.co.kr/eto/economy_news.xml"},
]

# ---------------------------------------------------------------------------
# 2) 스코어링 키워드
# ---------------------------------------------------------------------------
# 단독·취재 신호 (부장 전화 / 후배 확인용) — 최상단 가중
SCOOP_STRONG = ["[단독]", "단독", "[특종]", "특종"]
SCOOP_SOFT = ["[인터뷰]", "[단독 인터뷰]", "[르포]", "[기획]", "[집중취재]",
              "[이슈&", "[단독인터뷰]", "인터뷰]", "[분석]"]

# 중기부·중견·중소·벤처 (담당 분야 1순위)
KW_SME = [
    "중기부", "중소벤처기업부", "중소기업", "중견기업", "소상공인", "자영업",
    "벤처기업", "벤처투자", "벤처캐피탈", "스타트업", "창업", "벤처", "스케일업",
    "모태펀드", "팁스", "TIPS", "규제자유특구", "규제특례", "납품대금", "납품단가",
    "기술탈취", "기술유용", "상생", "가업승계", "중소기업중앙회", "중기중앙회",
    "벤처기업협회", "이노비즈", "메인비즈", "소진공", "소상공인시장진흥공단",
    "정책자금", "정책금융", "스마트공장", "백년가게", "협동조합", "기업승계",
    "중소벤처", "벤처펀드", "유니콘", "딥테크", "글로벌 강소",
]

# 바이오·제약·헬스케어 (담당 분야 1순위)
KW_BIO = [
    "바이오", "제약", "신약", "임상", "식약처", "FDA", "셀트리온", "삼성바이오",
    "삼성바이오로직스", "바이오헬스", "진단", "체외진단", "의료기기", "디지털치료",
    "ADC", "세포치료", "유전자치료", "백신", "헬스케어", "바이오시밀러",
    "원료의약품", "CDMO", "CMO", "위탁생산", "임상시험", "품목허가", "혁신신약",
    "펩타이드", "항체", "mRNA", "줄기세포", "K바이오", "K-바이오", "국산신약",
    "희귀질환", "항암제", "면역항암", "바이오벤처", "메디컬", "에스테틱",
]

# 정부·정책 일반
KW_POLICY = [
    "정부", "국회", "부처", "장관", "정책", "예산", "규제", "공정위", "금융위",
    "산업부", "기재부", "R&D", "지원사업", "인증", "세제", "개편안", "육성",
    "국정감사", "국감", "법안", "시행령", "고시",
]

# "무슨 일 났나" 시그널 (후배 확인·이슈 추적)
KW_EVENT = [
    "인수", "합병", "M&A", "상장", "IPO", "유상증자", "투자유치", "시리즈",
    "매각", "최대 실적", "역대 최대", "흑자전환", "적자", "리콜", "압수수색",
    "검찰", "구속", "논란", "파산", "회생", "워크아웃", "기소", "제재", "과징금",
    "횡령", "배임", "특허분쟁", "소송", "철수", "감원", "구조조정",
]


def contains_any(text, words):
    hits = 0
    for w in words:
        if w in text:
            hits += 1
    return hits


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw


def parse_date(s):
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(KST)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt.astimezone(KST)
        except Exception:
            continue
    return None


def strip_tags(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return html.unescape(s).strip()


def norm_title(t):
    t = re.sub(r"\[[^\]]*\]", "", t)         # 대괄호 태그 제거
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", t)   # 기호·공백 제거
    return t.lower()


def parse_feed(raw, source):
    """RSS 2.0 / Atom 양쪽 관용 파싱."""
    items = []
    try:
        root = ET.fromstring(raw)
    except Exception:
        # 인코딩 이슈 대비: bytes 그대로 재시도 실패 시 포기
        try:
            root = ET.fromstring(raw.decode("utf-8", "ignore"))
        except Exception:
            return items

    # RSS
    nodes = root.findall(".//item")
    is_atom = False
    if not nodes:
        # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        nodes = root.findall(f".//{ns}entry")
        is_atom = True

    for n in nodes:
        if is_atom:
            ns = "{http://www.w3.org/2005/Atom}"
            title = (n.findtext(f"{ns}title") or "").strip()
            link_el = n.find(f"{ns}link")
            link = link_el.get("href") if link_el is not None else ""
            date_s = n.findtext(f"{ns}updated") or n.findtext(f"{ns}published")
            desc = n.findtext(f"{ns}summary") or ""
        else:
            title = (n.findtext("title") or "").strip()
            link = (n.findtext("link") or "").strip()
            date_s = n.findtext("pubDate") or n.findtext("date") or \
                n.findtext("{http://purl.org/dc/elements/1.1/}date")
            desc = n.findtext("description") or ""

        title = strip_tags(title)
        if not title or not link:
            continue
        items.append({
            "title": title,
            "link": link.strip(),
            "date": parse_date(date_s),
            "desc": strip_tags(desc)[:200],
            "outlet": source["outlet"],
            "kind": source["kind"],
            "weight": source["weight"],
        })
    return items


def classify_and_score(a, now):
    title = a["title"]
    text = title + " " + a["desc"]

    score = float(a["weight"])
    tags = []          # (label, css-class) 표시용 칩
    is_scoop = False

    # 단독·취재
    if any(k in title for k in SCOOP_STRONG):
        score += 55
        is_scoop = True
        tags.append(("단독", "chip-scoop"))
    elif any(k in title for k in SCOOP_SOFT):
        score += 16
        is_scoop = True
        tags.append(("취재", "chip-scoop"))

    sme = contains_any(text, KW_SME)
    bio = contains_any(text, KW_BIO)
    pol = contains_any(text, KW_POLICY)
    evt = contains_any(text, KW_EVENT)

    score += min(sme, 3) * 13
    score += min(bio, 3) * 11
    score += min(pol, 2) * 6
    score += min(evt, 2) * 6

    # 카테고리 칩 (스코어 큰 쪽 우선)
    if sme:
        tags.append(("중기·벤처", "chip-sme"))
    if bio:
        tags.append(("바이오", "chip-bio"))
    if pol and not sme and not bio:
        tags.append(("정책", "chip-policy"))
    if evt and not sme and not bio and not pol:
        tags.append(("이슈", "chip-venture"))

    # 최신성 보너스 (24시간 내 최대 +24, 이후 감소)
    if a["date"]:
        hours = (now - a["date"]).total_seconds() / 3600.0
        a["hours"] = hours
        score += max(0.0, 26.0 - hours) if hours >= 0 else 10.0
    else:
        a["hours"] = 999.0

    # 주 카테고리 (섹션 배치용)
    if is_scoop:
        primary = "scoop"
    elif sme and bio:
        primary = "sme" if sme >= bio else "bio"
    elif sme:
        primary = "sme"
    elif bio:
        primary = "bio"
    elif pol:
        primary = "policy"
    else:
        primary = "front"

    a["score"] = score
    a["tags"] = tags[:3]
    a["is_scoop"] = is_scoop
    a["primary"] = primary
    a["cat_hits"] = {"sme": sme, "bio": bio, "pol": pol, "evt": evt}
    return a


def next_update_slot(now):
    """평일 06:00·14:00, 금 13:00(오후) 다음 슬롯 계산."""
    def slots_for(d):
        wd = d.weekday()  # 0=월 ... 4=금
        if wd == 4:       # 금요일
            return [6, 13]
        if wd < 4:        # 월~목
            return [6, 14]
        return []         # 주말 없음
    probe = now
    for _ in range(0, 8):
        for h in slots_for(probe):
            cand = probe.replace(hour=h, minute=0, second=0, microsecond=0)
            if cand > now:
                return cand
        probe = (probe + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return now + timedelta(days=1)


WD_KR = ["월", "화", "수", "목", "금", "토", "일"]


def fmt_dt(dt):
    return f"{dt.strftime('%Y-%m-%d')} ({WD_KR[dt.weekday()]}) {dt.strftime('%H:%M')}"


def fmt_short(dt):
    if not dt:
        return ""
    return dt.strftime("%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 3) 렌더링
# ---------------------------------------------------------------------------
def esc(s):
    return html.escape(s or "", quote=True)


def chips_html(tags):
    return "".join(f'<span class="chip {cls}">{esc(lbl)}</span>' for lbl, cls in tags)


def mr_item_html(i, a):
    top = " top3" if i <= 3 else ""
    return f"""      <li class="mr-item{top}">
        <span class="rank">{i}</span>
        <div class="mr-body">
          <div class="chips">{chips_html(a['tags'])}</div>
          <a class="mr-title" href="{esc(a['link'])}" target="_blank" rel="noopener">{esc(a['title'])}</a>
          <div class="mr-src"><b>{esc(a['outlet'])}</b> · {esc(a['kind'])} · {fmt_short(a['date'])}</div>
        </div>
      </li>"""


def art_item_html(a):
    tag = ""
    if a["is_scoop"]:
        tag = '<span class="tag">단독·취재</span>'
    return f"""        <li class="art-item">
          <a href="{esc(a['link'])}" target="_blank" rel="noopener">{esc(a['title'])}</a>
          <div class="art-src">{tag}<b>{esc(a['outlet'])}</b> · {esc(a['kind'])} · {fmt_short(a['date'])}</div>
        </li>"""


def section_html(title, desc, articles, accent=False):
    if not articles:
        body = '<p class="empty">현재 집계된 기사가 없습니다.</p>'
    else:
        body = '<ul class="art-list">\n' + \
               "\n".join(art_item_html(a) for a in articles) + "\n        </ul>"
    cls = "block block-head-accent" if accent else "block"
    return f"""    <section class="{cls}">
      <h2 class="block-title">{esc(title)}</h2>
      <p class="block-desc">{esc(desc)}</p>
      <div class="cols">
{body}
      </div>
    </section>"""


def render(must_read, sections, meta):
    mr = "\n".join(mr_item_html(i + 1, a) for i, a in enumerate(must_read))
    sec_html = "\n".join(sections)
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>중기부·바이오 데스크 브리핑 · {meta['date_short']}</title>
<meta name="description" content="중견·중소기업 + 바이오 담당 기자 필독 기사 자동 브리핑. 평일 06:00·14:00(금 13:00) 갱신.">
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" as="style" crossorigin
      href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<link rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700;800&display=swap">
<link rel="stylesheet" href="./style.css">
</head>
<body>
<header class="masthead">
  <div class="masthead-inner">
    <div class="kicker">DESK BRIEFING · 중기부 &amp; 바이오</div>
    <h1 class="brand">중기부·바이오 데스크 브리핑</h1>
    <p class="tagline">중견·중소기업 + 벤처 + 바이오 담당 필독 기사 — 부장 전화·후배 확인 대비용. 평일 06:00·14:00(금 13:00) 자동 갱신.</p>
    <div class="meta">
      <span><strong>업데이트</strong> {meta['updated']} KST</span>
      <span class="dot">●</span>
      <span><strong>다음 갱신</strong> {meta['next']}</span>
      <span class="dot">●</span>
      <span>수집 {meta['total']}건 · 필독 {meta['mr_count']}건</span>
    </div>
  </div>
</header>
<main>
    <section class="block">
      <h2 class="block-title">오늘의 필독 <span class="count">TOP {meta['mr_count']}</span></h2>
      <p class="block-desc">놓치면 안 되는 순서 — 단독·취재 &gt; 중기부 정책 &gt; 담당 기업/바이오 이슈 &gt; 주요 동향</p>
      <ol class="mustread-list">
{mr}
      </ol>
    </section>
{sec_html}
</main>
<footer>
  <div class="footer-inner">
    <h4>수집 매체</h4>
    <div class="src-list">{meta['sources']}</div>
    <p class="footer-note">
      본 페이지는 국내 경제지 RSS를 자동 수집·선별해 <b>{esc('중견·중소기업(중기부) + 바이오')}</b> 담당 기자의 필독 기사를 한눈에 모아 줍니다.
      단독·취재 기사, 중기부 정책, 담당 기업/바이오 이슈, 인수·상장·수사 등 주요 동향을 우선 노출합니다.
      각 제목을 클릭하면 원문으로 이동합니다. 스코어링은 키워드·최신성·매체 섹션 가중치 기반이며, 편집상 참고용입니다.<br>
      RSS 콘텐츠 저작권은 각 매체에 있으며, 개인 열람 목적의 비상업적 큐레이션입니다.
      자동 생성: GitHub Actions · 배포: Vercel · 갱신 {meta['updated']} KST.
    </p>
  </div>
</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 4) 메인
# ---------------------------------------------------------------------------
def main():
    now = datetime.now(KST)
    all_items = []
    ok_sources = []
    for src in SOURCES:
        try:
            raw = fetch(src["url"])
            items = parse_feed(raw, src)
            if items:
                ok_sources.append(f"{src['outlet']}·{src['kind']}")
                all_items.extend(items)
                print(f"[ok] {src['outlet']} {src['kind']}: {len(items)}건")
            else:
                print(f"[empty] {src['outlet']} {src['kind']}")
        except Exception as e:
            print(f"[fail] {src['outlet']} {src['kind']}: {e}", file=sys.stderr)

    # 중복 제거 (링크 + 정규화 제목)
    seen_link, seen_title, uniq = set(), set(), []
    for a in all_items:
        nt = norm_title(a["title"])
        if a["link"] in seen_link or (nt and nt in seen_title):
            continue
        seen_link.add(a["link"])
        if nt:
            seen_title.add(nt)
        uniq.append(a)

    # 스코어링
    for a in uniq:
        classify_and_score(a, now)

    # 48시간 이내만 (날짜 없으면 유지)
    fresh = [a for a in uniq if a["hours"] <= 48 or a["hours"] >= 998]
    fresh.sort(key=lambda x: x["score"], reverse=True)

    # 필독 TOP (최대 18)
    must_read = fresh[:18]
    mr_links = {a["link"] for a in must_read}

    # 섹션 분류 (필독 제외, 각 섹션 최신·점수순 상위)
    def pick(primary, limit, extra=None):
        out = []
        for a in fresh:
            if a["link"] in mr_links:
                continue
            if a["primary"] == primary or (extra and extra(a)):
                out.append(a)
            if len(out) >= limit:
                break
        return out

    sec_scoop = [a for a in fresh if a["is_scoop"] and a["link"] not in mr_links][:12]
    sec_sme = pick("sme", 14, extra=lambda a: a["cat_hits"]["sme"] and not a["is_scoop"])
    sec_bio = pick("bio", 14, extra=lambda a: a["cat_hits"]["bio"] and not a["is_scoop"])
    sec_policy = pick("policy", 10)
    # 1면·종합: 남은 상위 일반 기사
    used = mr_links | {a["link"] for a in sec_scoop + sec_sme + sec_bio + sec_policy}
    sec_front = [a for a in fresh if a["link"] not in used][:14]

    sections = [
        section_html("🔴 단독·취재", "부장 전화·후배 확인 1순위 — 우리가 놓치면 안 되는 발제·특종",
                     sec_scoop, accent=True),
        section_html("🏛 중기부·중견·중소·벤처", "정책·지원사업·현장 — 담당 분야 핵심",
                     sec_sme),
        section_html("🧬 바이오·제약·헬스케어", "신약·임상·규제·주요사 실적",
                     sec_bio),
        section_html("📋 정부·정책 일반", "부처·국회·규제 동향",
                     sec_policy),
        section_html("📰 1면·종합 경제", "전반 흐름 파악용 주요 경제 기사",
                     sec_front),
    ]

    src_html = " · ".join(sorted(set(s.split("·")[0] for s in ok_sources)))
    meta = {
        "updated": fmt_dt(now),
        "date_short": now.strftime("%Y-%m-%d"),
        "next": fmt_dt(next_update_slot(now)),
        "total": len(uniq),
        "mr_count": len(must_read),
        "sources": esc(src_html) if src_html else "수집 실패",
    }

    doc = render(must_read, sections, meta)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"[done] {OUT} — 총 {len(uniq)}건, 필독 {len(must_read)}건, 소스 {len(ok_sources)}개")


if __name__ == "__main__":
    main()
