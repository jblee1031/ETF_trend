# ETF Trend Dashboard

국내(KRX) 상장 ETF와 미국 주식/ETF를 그룹별로 묶어서 종가 트렌드 차트와 종가 테이블을 보여주는 정적 웹 대시보드입니다.
GitHub Actions가 각 시장 마감 후 자동으로 데이터를 갱신하고, GitHub Pages로 웹에서 바로 볼 수 있습니다.

## 구성

| 시장 | 그룹 정의 | 수집 데이터 | 수집 스크립트 | 데이터 소스 |
|---|---|---|---|---|
| 국내 ETF | `data/groups.json` | `data/prices.json` | `scripts/fetch_prices.py` | 네이버 금융 |
| 미국 주식/ETF | `data/us_groups.json` | `data/us_prices.json` | `scripts/fetch_us_prices.py` | Yahoo Finance |

- `index.html` — 국내/미국 탭 전환, 그룹별 차트 + 종가 테이블 렌더링 (Chart.js 사용, 별도 빌드 과정 없음)
- `.github/workflows/update.yml` — 국내용, 평일 15:40 KST 자동 실행
- `.github/workflows/update_us.yml` — 미국용, 평일 06:30 KST 자동 실행
- 그룹/종목 정의 파일(`*_groups.json`)만 수정하면 그룹·종목을 바로 바꿀 수 있습니다. `prices.json`류는 워크플로우가 덮어쓰므로 직접 수정하지 마세요.

## 자동 업데이트

- **국내**: 매 평일 **15:40 KST** (국내 장마감 15:30 이후)
- **미국**: 매 평일 **06:30 KST** (미 동부 16:00 마감 기준, 서머타임(EDT)이든 표준시(EST)든 여유 있게 반영되는 시각)
- 두 워크플로우 모두 GitHub Actions가 데이터를 갱신하고 자동 커밋/푸시하면, GitHub Pages가 `main` 브랜치 push를 감지해 자동 재배포합니다.
- 데이터에 변경이 없으면(휴장일 등) 커밋하지 않습니다.
- GitHub 정책상 **60일간 저장소에 아무 활동이 없으면 스케줄 워크플로우가 자동 비활성화**됩니다. 두 워크플로우가 평일마다 커밋을 만들기 때문에 정상적으로는 계속 활성 상태가 유지됩니다.
- Actions 탭에서 각 워크플로우를 "Run workflow"로 수동 실행할 수도 있습니다.

## 로컬에서 미리보기

```bash
pip install -r requirements.txt
python scripts/fetch_prices.py      # data/prices.json 갱신 (국내)
python scripts/fetch_us_prices.py   # data/us_prices.json 갱신 (미국)
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
- 미국: `data/us_groups.json`에서 수정합니다. 코드는 Yahoo Finance 티커 심볼입니다 (예: `AAPL`, `BRK-A`). 국내 증권사 앱에서 보이는 코드(`NDAAPL`, `NYUBER` 등)는 거래소 접두사(ND=나스닥, NY=NYSE, NA=NYSE American)를 뺀 나머지가 실제 티커입니다.

## 향후 확장

- 미국 주식/ETF는 구현 완료. 다른 시장(일본, 중국 A주 등)을 추가하려면 같은 패턴으로 `data/<market>_groups.json` + `scripts/fetch_<market>_prices.py` + 워크플로우를 하나 더 만들고, `index.html`에 탭을 하나 더 추가하면 됩니다.
