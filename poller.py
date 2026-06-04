#!/usr/bin/env python3
"""
IPO Radar — 미국 IPO 최속 알림 폴러

신호 우선순위
  1) SEC EDGAR Atom 피드  : 공시가 뜨는 즉시(초 단위) → "누구보다 빨리"의 핵심
       - S-1 / F-1   : 신규 종목 '등장' 자체 (상장 의향 최초 공개)
       - 424B4/424B1 : 공모가 확정 = 상장 임박 (보통 상장 1~2일 전 저녁)
       - 8-A12B      : 거래소 등록 = 상장 직전 강한 신호
  2) Finnhub IPO 캘린더    : 예상 상장일 · 티커 · 가격범위 · status 보강

알림 채널 (env 있는 것만 동작)
  - ntfy.sh   (NTFY_TOPIC)          → 안드로이드 즉시 푸시
  - Discord   (DISCORD_WEBHOOK)
  - Telegram  (TELEGRAM_TOKEN + TELEGRAM_CHAT_ID)

상태(seen.json)는 이미 알린 건 스킵하기 위한 dedupe 저장소.
GitHub Actions 가 매 실행 후 repo 에 커밋해 영속화한다.

최초 실행(seen.json 없음)에는 폭주 방지를 위해 과거 항목을 '조용히' 채워넣고
"레이더 가동" 한 줄만 보낸다.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

try:
    import feedparser
except ImportError:
    print("feedparser 미설치: pip install feedparser", file=sys.stderr)
    raise

# ── 설정 ──────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
SEEN_PATH = os.path.join(HERE, "seen.json")

# SEC 는 연락처가 담긴 User-Agent 를 요구한다 (없으면 차단).
SEC_UA = os.environ.get("SEC_UA", "dododong.dev ipo-radar gemiddikku@gmail.com")

# 감시할 공시 폼 타입. 의미는 상단 docstring 참고.
EDGAR_FORMS = ["S-1", "F-1", "424B4", "424B1", "8-A12B"]

EDGAR_FEED = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type={form}&output=atom&count=100"
)

FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "").strip()
FINNHUB_URL = "https://finnhub.io/api/v1/calendar/ipo"

# 신호별 우선순위(ntfy priority) 와 태그(이모지)
SIGNAL_META = {
    "424B4":  ("urgent", "rotating_light", "공모가 확정·상장 임박"),
    "424B1":  ("urgent", "rotating_light", "공모가 확정·상장 임박"),
    "8-A12B": ("high",   "white_check_mark", "거래소 등록·상장 직전"),
    "S-1":    ("default", "new", "신규 상장 의향 (S-1)"),
    "F-1":    ("default", "new", "신규 상장 의향·해외기업 (F-1)"),
}

PRUNE_DAYS = 60  # seen.json 이 무한정 커지지 않도록 오래된 항목 정리

# ── 상태 입출력 ────────────────────────────────────────────────────────────────
def load_seen():
    if not os.path.exists(SEEN_PATH):
        return None  # 최초 실행 신호
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_seen(items):
    # 오래된 항목 정리
    cutoff = datetime.now(timezone.utc) - timedelta(days=PRUNE_DAYS)
    pruned = {}
    for k, v in items.items():
        try:
            first = datetime.fromisoformat(v["first_seen"])
        except (KeyError, ValueError):
            first = datetime.now(timezone.utc)
        if first >= cutoff:
            pruned[k] = v
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"updated": now_iso(), "items": pruned}, f,
                  ensure_ascii=False, indent=2)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ── 수집: SEC EDGAR ───────────────────────────────────────────────────────────
def fetch_edgar():
    """[(uid, form, company, link, when)] 반환."""
    out = []
    headers = {"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}
    for form in EDGAR_FORMS:
        url = EDGAR_FEED.format(form=form)
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[EDGAR {form}] 요청 실패: {e}", file=sys.stderr)
            continue
        feed = feedparser.parse(resp.content)
        for entry in feed.entries:
            uid = entry.get("id") or entry.get("link")
            if not uid:
                continue
            title = entry.get("title", "")
            company = parse_company(title)
            link = entry.get("link", "")
            when = entry.get("updated", "") or entry.get("published", "")
            out.append((f"edgar:{uid}", form, company, link, when))
        time.sleep(0.4)  # SEC 예의상 간격
    return out


def parse_company(title):
    # 형식 예: "424B4 - ACME INC (0001234567) (Filer)"
    # 폼명에 하이픈이 있어(S-1, 8-A12B) 구분자는 첫 " - "(공백 포함)로 자른다.
    rest = title.split(" - ", 1)[1] if " - " in title else title
    m = re.match(r"^(.+?)\s*\(\d+\)", rest)
    return m.group(1).strip() if m else rest.strip()


# ── 수집: Finnhub IPO 캘린더 ───────────────────────────────────────────────────
def fetch_finnhub():
    """[(uid, symbol, name, date, exchange, price, status)] 반환."""
    if not FINNHUB_KEY:
        return []
    today = datetime.now(timezone.utc).date()
    params = {
        "from": today.isoformat(),
        "to": (today + timedelta(days=40)).isoformat(),
        "token": FINNHUB_KEY,
    }
    try:
        resp = requests.get(FINNHUB_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[Finnhub] 요청 실패: {e}", file=sys.stderr)
        return []
    out = []
    for ipo in data.get("ipoCalendar", []):
        symbol = ipo.get("symbol") or ""
        name = ipo.get("name") or ""
        date = ipo.get("date") or ""
        exch = ipo.get("exchange") or ""
        price = ipo.get("price") or ""
        status = (ipo.get("status") or "").lower()  # expected/priced/filed/withdrawn
        uid = f"finnhub:{symbol or name}:{date}"
        out.append((uid, symbol, name, date, exch, price, status))
    return out


# ── 알림 전송 ──────────────────────────────────────────────────────────────────
def send_ntfy(title, body, priority="default", tags=None):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    base = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)
    try:
        requests.post(f"{base}/{topic}", data=body.encode("utf-8"),
                      headers=headers, timeout=15)
    except requests.RequestException as e:
        print(f"[ntfy] 전송 실패: {e}", file=sys.stderr)


def send_discord(content):
    url = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not url:
        return
    try:
        requests.post(url, json={"content": content[:1900]}, timeout=15)
    except requests.RequestException as e:
        print(f"[discord] 전송 실패: {e}", file=sys.stderr)


def send_telegram(text):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000],
                  "disable_web_page_preview": False},
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"[telegram] 전송 실패: {e}", file=sys.stderr)


def broadcast(title, body, priority="default", tags=None):
    send_ntfy(title, body, priority, tags)
    full = f"{title}\n{body}"
    send_discord(full)
    send_telegram(full)


# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    seen = load_seen()
    first_run = seen is None
    if first_run:
        seen = {}

    new_items = []  # (priority, title, body, tags)

    # 1) EDGAR
    for uid, form, company, link, when in fetch_edgar():
        prev = seen.get(uid)
        if prev is not None:
            continue
        seen[uid] = {"first_seen": now_iso(), "status": form}
        if first_run:
            continue
        prio, tag, label = SIGNAL_META.get(form, ("default", "page_facing_up", form))
        title = f"[{form}] {company}"
        body = f"{label}\n{link}"
        new_items.append((prio, title, body, [tag]))

    # 2) Finnhub (신규 등장 + status 변경 모두 감지)
    for uid, symbol, name, date, exch, price, status in fetch_finnhub():
        prev = seen.get(uid)
        changed = prev is None or prev.get("status") != status
        seen[uid] = {"first_seen": (prev or {}).get("first_seen", now_iso()),
                     "status": status}
        if first_run or not changed:
            continue
        # status 별 우선순위
        if status == "priced":
            prio, tag = "urgent", "rotating_light"
        elif status == "expected":
            prio, tag = "high", "calendar"
        elif status == "withdrawn":
            prio, tag = "low", "x"
        else:
            prio, tag = "default", "memo"
        sym = f"${symbol} " if symbol else ""
        title = f"[IPO {status or 'update'}] {sym}{name}".strip()
        lines = [f"상장예정일: {date or '미정'}"]
        if exch:
            lines.append(f"거래소: {exch}")
        if price:
            lines.append(f"공모가: {price}")
        body = "\n".join(lines)
        new_items.append((prio, title, body, [tag]))

    save_seen(seen)

    if first_run:
        broadcast(
            "📡 IPO Radar 가동",
            f"감시 시작. 폼 {', '.join(EDGAR_FORMS)} + Finnhub 캘린더.\n"
            f"과거 {len(seen)}건은 조용히 등록했고, 지금부터 새 항목만 알립니다.",
            priority="default", tags=["satellite"],
        )
        print(f"최초 실행: {len(seen)}건 시드 완료.")
        return

    # 긴급 신호 먼저
    order = {"urgent": 0, "high": 1, "default": 2, "low": 3, "min": 4}
    new_items.sort(key=lambda x: order.get(x[0], 2))
    for prio, title, body, tags in new_items:
        broadcast(title, body, priority=prio, tags=tags)
        time.sleep(0.3)

    print(f"신규 알림 {len(new_items)}건 전송.")


if __name__ == "__main__":
    main()
