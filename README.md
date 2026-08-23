# ETF Trend Dashboard

국내(KRX) 상장 ETF들을 그룹별로 묶어서 종가 트렌드 차트와 종가 테이블을 보여주는 정적 웹 대시보드입니다.
GitHub Actions가 평일 장마감 후 자동으로 데이터를 갱신하고, GitHub Pages로 웹에서 바로 볼 수 있습니다.

## 구성

- `data/groups.json` — ETF 그룹 정의 (그룹명 + 종목코드/종목명 목록). **여기만 수정하면 그룹/종목을 바꿀 수 있습니다.**
- `data/prices.json` — 자동 수집된 종가 데이터 (직접 수정하지 마세요, 워크플로우가 매일 덮어씁니다)
- `scripts/fetch_prices.py` — 네이버 금융에서 종가를 가져와 `data/prices.json`을 생성하는 스크립트
- `index.html` — 그룹별 차트 + 종가 테이블을 렌더링하는 페이지 (Chart.js 사용, 별도 빌드 과정 없음)
- `.github/workflows/update.yml` — 평일 15:40(KST) 자동 실행 + 수동 실행(workflow_dispatch) 워크플로우

## 자동 업데이트

- 매 평일 **15:40 KST** (국내 장마감 15:30 이후) 에 GitHub Actions가 실행되어 `data/prices.json`을 갱신하고 자동으로 커밋/푸시합니다.
- GitHub Pages는 `main` 브랜치 push를 감지해 자동으로 재배포합니다.
- 데이터에 변경이 없으면(공휴일 등) 커밋하지 않습니다.
- GitHub의 정책상 **60일간 저장소에 아무 활동이 없으면 스케줄 워크플로우가 자동으로 비활성화**됩니다. 이 워크플로우는 평일마다 커밋을 만들기 때문에 정상적으로는 계속 활성 상태가 유지됩니다.
- Actions 탭에서 언제든 "Run workflow" 버튼으로 수동 실행도 가능합니다.

## 로컬에서 미리보기

```bash
pip install -r requirements.txt
python scripts/fetch_prices.py   # data/prices.json 갱신
python -m http.server 8000       # 아무 정적 서버든 사용 가능
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

`data/groups.json`에 그룹을 추가하거나 종목을 넣고 빼면 됩니다. 코드는 KRX 종목코드(6자리 숫자 또는 영문 포함 코드, 예: `0072R0`)를 그대로 사용합니다.

## 향후 확장 (해외 ETF)

현재는 국내 상장 ETF만 지원합니다. 미국 등 해외 ETF를 추가하려면:
- 별도 데이터 소스(예: yfinance) 연동 필요
- 미국 장마감(미 동부 16:00) 기준 업데이트 스케줄 추가 필요 (서머타임에 따라 한국시간 05:40 또는 06:40)
