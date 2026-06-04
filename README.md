# IPO Radar 📡

미국(NYSE/NASDAQ) IPO를 **누구보다 빨리** 알림받는 무인 폴러.
SEC EDGAR 공시 피드(초 단위 최속 신호) + Finnhub IPO 캘린더를 합쳐
신규 상장 의향 → 공모가 확정 → 상장 임박 단계마다 푸시한다.

## 어떤 신호를 잡나

| 폼/상태 | 의미 | 우선순위 |
|---|---|---|
| `S-1` / `F-1` | 신규 종목 '등장' 자체 (상장 의향 최초 공개) | 보통 |
| Finnhub `expected` | 예상 상장일 잡힘 | 높음 |
| `424B4` / `424B1`, Finnhub `priced` | **공모가 확정 = 상장 1~2일 전** | 긴급 |
| `8-A12B` | 거래소 등록 = 상장 직전 | 높음 |

> EDGAR RSS 는 공시 게시 즉시 나온다. 사람이 정리해 올리는 캘린더 사이트보다 빠르다 — 이게 "남보다 빨리"의 핵심.

## 알림 채널 (켜둔 것만 동작)

- **ntfy.sh** → 안드로이드 즉시 푸시 (앱 설치 + 토픽 구독)
- **Discord** 웹훅
- **Telegram** 봇

## 셋업 (≈15분)

### 1. GitHub 리포 생성 후 이 폴더 push
```bash
cd "K:/Claude Project/ipo_radar"
git init
git add .
git commit -m "init: IPO Radar"
git branch -M main
git remote add origin https://github.com/<당신>/ipo-radar.git
git push -u origin main
```

### 2. Finnhub 무료 키 발급
https://finnhub.io 가입(카드 불필요) → API key 복사.

### 3. ntfy 안드로이드 설정
1. Play 스토어에서 **ntfy** 앱 설치
2. `+` → 추측 어려운 토픽명 구독 (예: `dododong-ipo-9f3k2`)
3. 같은 토픽명을 아래 `NTFY_TOPIC` 시크릿에 등록

### 4. GitHub Secrets 등록
리포 → Settings → Secrets and variables → Actions → **New repository secret**

| 이름 | 값 | 필수 |
|---|---|---|
| `FINNHUB_KEY` | Finnhub 키 | 권장 |
| `NTFY_TOPIC` | 구독한 ntfy 토픽명 | 안드로이드용 |
| `DISCORD_WEBHOOK` | 디스코드 채널 웹훅 URL | 선택 |
| `TELEGRAM_TOKEN` | 텔레그램 봇 토큰 | 선택 |
| `TELEGRAM_CHAT_ID` | 받을 chat id | 선택 |
| `NTFY_SERVER` | 자체 ntfy 서버 쓸 때만 | 선택 |
| `SEC_UA` | 연락처 포함 UA (미설정 시 기본값) | 선택 |

### 5. 첫 실행
Actions 탭 → **IPO Radar** → *Run workflow*.
- 최초 실행은 과거 항목을 **조용히** 등록하고 "📡 IPO Radar 가동" 한 줄만 보냄(폭주 방지).
- 이후 10분마다 자동 실행, 새 항목만 푸시.

## 로컬 테스트
```bash
cp .env.example .env   # 값 채우기
set -a; source .env; set +a
pip install -r requirements.txt
python poller.py
```
`seen.json` 을 지우면 '최초 실행'으로 리셋된다.

## 튜닝 포인트
- 감시 폼 추가/제외: `poller.py` 의 `EDGAR_FORMS`
- 실행 주기: `.github/workflows/ipo-radar.yml` 의 `cron` (최소 5분, 실제 10~15분)
- 안드로이드 전용 앱(FCM)으로 갈아끼우는 Phase 2 는 ntfy 채널을 대체하면 됨.

## 한계 / 주의
- GitHub cron 은 best-effort라 부하 시 지연될 수 있음. 초 단위가 필요하면 상시 구동 호스트로 이전.
- 미국 IPO 공모가에 일반 한국 개인이 청약 참여하는 건 증권사 제약이 큼. 이 도구는 **상장 첫 거래 매수 타이밍**을 빠르게 잡는 데 최적.
- Finnhub 무료 티어 한도(60콜/분) 안에서 동작.
