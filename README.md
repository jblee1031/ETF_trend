# ETF Trend Dashboard

국내(KRX) 상장 ETF, 미국 주식/ETF, 그리고 코스피200·코스닥150의 이동평균선 정배열 종목을 한 곳에서 보는 정적 웹 대시보드입니다.
GitHub Actions가 각 시장 마감 후 자동으로 데이터를 갱신하고, GitHub Pages로 웹에서 바로 볼 수 있습니다.

## 구성

| 탭 | 종목 정의 | 수집 데이터 | 수집 스크립트 | 데이터 소스 |
|---|---|---|---|---|
| 국내 ETF | `data/groups.json` | `data/prices.json` | `scripts/fetch_prices.py` | 네이버 금융 |
| 미국 주식/ETF | `data/us_groups.json` | `data/us_prices.json` | `scripts/fetch_us_prices.py` | Yahoo Finance |
| 코스피200 정배열 | 자동 수집 (`data/kospi200_tickers.json`에 기록) | `data/kospi200_signals.json` | `scripts/fetch_kospi200.py` | 네이버 금융 |
| 코스닥150 정배열 | 자동 수집 (`data/kosdaq150_tickers.json`에 기록) | `data/kosdaq150_signals.json` | `scripts/fetch_kosdaq150.py` | KODEX 코스닥150 구성종목 + 네이버 금융 |

- `index.html` — 탭 전환 + 차트/테이블 렌더링 (Chart.js 사용, 별도 빌드 과정 없음)
- `scripts/krx_alignment.py` — 정배열 두 탭이 공유하는 파이프라인 (시세·이평선·스냅샷·섹터·추세템플릿). 직접 실행하지 않습니다.
- `.github/workflows/update_kr.yml` — 국내 ETF + 코스피200 + 코스닥150, 매일 20:05 KST 자동 실행
- `.github/workflows/update_us.yml` — 미국용, 평일 06:30 KST 자동 실행
- 그룹/종목 정의 파일(`*_groups.json`)만 수정하면 그룹·종목을 바로 바꿀 수 있습니다. `prices.json`·`*_signals.json`·`*_tickers.json`류는 워크플로우가 덮어쓰므로 직접 수정하지 마세요.

## 정배열 탭 (코스피200 / 코스닥150)

두 탭은 구성종목만 다르고 화면과 계산 로직은 같습니다. 각 종목의 5·10·20·60·120일 이동평균선을 계산해 네 개 섹션으로 보여줍니다.

1. **단기 정배열** — `MA5 > MA10 > MA20`
2. **완전 정배열** — `MA5 > MA10 > MA20 > MA60 > MA120` (해당 종목들의 종가 트렌드 차트 포함)
3. **섹터 분포** — 섹터별 종목 수 Pareto 차트 (막대 + 누적 비중). 막대를 클릭하면 그 섹터의 종목 목록이 아래에 펼쳐집니다.
4. **미네르비니 추세 템플릿** — 아래 참조

- 상단 **기준일** 드롭다운으로 최근 40거래일(약 2개월) 중 아무 날이나 골라 "그날 기준 정배열이었던 종목"을 조회할 수 있습니다. 차트도 선택한 기준일까지만 그려집니다.
- 테이블에는 종목명과 함께 **섹터**와 **시가총액**이 표시됩니다.
- 툴바의 **정렬**(`연속일순` / `시가총액순`)과 **섹터별 묶기**는 1·2번 리스트에 함께 적용됩니다. 묶어서 볼 때 섹터는 소속 종목의 시가총액 합계(시가총액순) 또는 종목 수(연속일순) 기준으로 정렬되고, 각 섹터 머리줄에 종목 수와 시총 합계가 표시됩니다.
- **연속일** 컬럼은 해당 조건이 며칠째 유지되고 있는지를 뜻하며, 당일 새로 진입한 종목에는 `신규` 배지가 붙습니다. 반대로 전 거래일에는 있었으나 당일 빠진 종목은 테이블 위에 **편출** 목록으로 따로 표시됩니다.
- 종목명을 클릭하면 [FnGuide Company Guide](https://wcomp.fnguide.com/)의 해당 종목 기업정보 페이지가 새 탭으로 열립니다.
- 매 실행마다 원본 시세에서 전체 스냅샷을 다시 계산하므로, 워크플로우가 하루 걸러도 과거 데이터에 구멍이 생기지 않습니다.
- 구성종목 리스트는 매 실행 시 새로 수집합니다. 수집이 실패하면 마지막으로 저장된 `*_tickers.json`을 사용해 계속 동작합니다.

### 미네르비니 추세 템플릿

단기 정배열 종목 중 마크 미네르비니(Mark Minervini)의 Trend Template 8개 조건을 **모두** 통과한 종목을 점수순으로 나열합니다.

| # | 조건 |
|---|---|
| 1 | 종가 > 150일선, 200일선 |
| 2 | 150일선 > 200일선 |
| 3 | 200일선이 최근 1개월(22거래일) 상승 |
| 4 | 50일선 > 150일선, 200일선 |
| 5 | 종가 > 50일선 |
| 6 | 52주 저점 대비 +30% 이상 |
| 7 | 52주 고점 대비 -25% 이내 |
| 8 | RS ≥ 70 |

통과 종목의 순위를 매기는 점수는 각 항을 0~100으로 정규화한 가중합입니다.

```
Score = 0.40 × RS
      + 0.30 × (100 − 고점이격%)
      + 0.15 × min(저점이격%, 200) ÷ 2
      + 0.15 × min(max(200일선 기울기%, 0), 10) × 10
```

- `RS` = `0.4·r(63일) + 0.2·r(126일) + 0.2·r(189일) + 0.2·r(252일)` 의 유니버스 내 백분위(0–99). `r(n)`은 n거래일 수익률이며, 상장 기간이 짧아 빠지는 구간은 가중치를 재정규화합니다.
- `고점이격` = `1 − 종가 / 52주 최고가`, `저점이격` = `종가 / 52주 최저가 − 1`
- `200일선 기울기` = 200일선의 22거래일 변화율

RS는 지수 전체가 아니라 **해당 탭의 유니버스(코스피200 또는 코스닥150) 안에서의 상대 순위**입니다. 기계적인 스크리닝 결과이며 매매 판단은 별도입니다.

## 자동 업데이트

- **국내 ETF + 코스피200 / 코스닥150 정배열**: **매일 20:05 KST** (`update_kr.yml`). 세 스크립트를 한 작업에서 순서대로 돌려 커밋을 하나로 만듭니다 — 같은 시각에 워크플로우가 따로 돌면 같은 브랜치로 push하다 충돌하기 때문입니다.
- **미국 주식/ETF**: 매 평일 **06:30 KST** (미 동부 16:00 마감 기준, 서머타임(EDT)이든 표준시(EST)든 여유 있게 반영되는 시각)
- 두 워크플로우 모두 GitHub Actions가 데이터를 갱신하고 자동 커밋/푸시하면, GitHub Pages가 `main` 브랜치 push를 감지해 자동 재배포합니다. 서로 겹쳐 돌아 push가 거절되면 rebase 후 최대 3번 재시도합니다.
- 데이터 내용이 그대로면(주말·휴장일 등) 파일을 다시 쓰지 않으므로 커밋도 생기지 않습니다.
- **예약 시각은 "실행 대기열에 넣는 시각"일 뿐 시작 시각이 보장되지 않습니다.** GitHub는 부하가 몰리면 스케줄 실행을 늦추거나 건너뛰며, 이 저장소에서는 실제로 2~12시간 늦게 시작된 기록이 있습니다. 급할 때는 Actions 탭에서 "Run workflow"로 바로 실행하세요.
- GitHub 정책상 **60일간 저장소에 아무 활동이 없으면 스케줄 워크플로우가 자동 비활성화**됩니다. 평일마다 데이터 커밋이 생기므로 정상적으로는 계속 활성 상태가 유지됩니다.
- Actions 탭에서 각 워크플로우를 "Run workflow"로 수동 실행할 수도 있습니다.

## 로컬에서 미리보기

```bash
pip install -r requirements.txt
python scripts/fetch_prices.py      # data/prices.json 갱신 (국내 ETF)
python scripts/fetch_us_prices.py   # data/us_prices.json 갱신 (미국)
python scripts/fetch_kospi200.py    # data/kospi200_signals.json 갱신 (약 3분 소요)
python scripts/fetch_kosdaq150.py   # data/kosdaq150_signals.json 갱신 (약 3분 소요)
python -m http.server 8000          # 아무 정적 서버든 사용 가능
# 브라우저에서 http://localhost:8000 접속
```

## GitHub에 올리고 웹으로 공개하기

1. GitHub에서 새 저장소 생성 (Public 권장 — GitHub Pages 무료 사용을 위해)
2. 로컬 저장소에 원격 연결 후 push
   ```bash
   git remote add origin https://github.com/<YOUR_USERNAME>/<REPO_NAME>.git
   git branch -M main
   git push -u origin main
   ```
3. 저장소 **Settings → Pages** 로 이동
   - Source: `Deploy from a branch`
   - Branch: `main` / `/(root)`
   - Save
4. 몇 분 후 `https://<YOUR_USERNAME>.github.io/<REPO_NAME>/` 에서 대시보드 확인
5. **Settings → Actions → General → Workflow permissions** 에서 "Read and write permissions"이 선택되어 있는지 확인 (자동 커밋을 위해 필요)

## 그룹/종목 추가·수정

- 국내: `data/groups.json`에 그룹을 추가하거나 종목을 넣고 빼면 됩니다. 코드는 KRX 종목코드(6자리 숫자 또는 영문 포함 코드, 예: `0072R0`)를 그대로 사용합니다.
- 정배열 두 탭은 구성종목을 자동 수집하므로 수정할 게 없습니다. 분기 리밸런싱도 다음 실행에 자동 반영됩니다.
- 미국: `data/us_groups.json`에서 수정합니다. 코드는 Yahoo Finance 티커 심볼입니다 (예: `AAPL`, `BRK-A`). 국내 증권사 앱에서 보이는 코드(`NDAAPL`, `NYUBER` 등)는 거래소 접두사(ND=나스닥, NY=NYSE, NA=NYSE American)를 뺀 나머지가 실제 티커입니다.

## 향후 확장

- 미국 주식/ETF는 구현 완료. 다른 시장(일본, 중국 A주 등)을 추가하려면 같은 패턴으로 `data/<market>_groups.json` + `scripts/fetch_<market>_prices.py` + 워크플로우를 하나 더 만들고, `index.html`에 탭을 하나 더 추가하면 됩니다.
