# 03. 수집기 (Liquipedia)

## 파일
- collector/wikitext.mjs   {{Template}} 파서 (완료)
- collector/liquipedia.mjs API 호출 + 캐시 + 경기 파싱 (완료, Stage 3 정규시즌 36경기 파싱 확인)
- collector/test-parse.mjs 시험

## 확인됨
- 정규시즌: 36경기 중 15경기 진행, POTM(mvp) 15개 일치, 날짜 전부 파싱.

## 할 일 (순서)
1. [ ] 대회 목록 찾기: 팀 페이지 `prop=links` + 시즌 개요 페이지에서 한국 대회 페이지 이름 모으기
2. [ ] 플레이오프 형식 파싱 ({{Bracket}} 계열) - 정규시즌과 다름
3. [ ] 과거 시즌 (Contenders 2020~2023, OWCS 2024~2026) 페이지 이름 규칙 확인
4. [ ] 팀 이름 정규화(aliases)
5. [ ] 전체 실행 -> data/lp/*.json
6. [ ] 규칙: 2.2초 간격, parse API 금지, HTML 긁기 금지, 출처 표기

## 폐기
- owtics 수집 코드(collector/collect.mjs, http.mjs, decode.mjs)는 쓰지 않음. 참고용으로만 보관.

## 진행 기록 (2026-10-11)
- 한국 대회 목록 작성: data/competitions.json (core: OWCS 2024~2026 한국/아시아/국제, legacy_contenders: 2018~2023, world_cup)
- 기존 자료 시트 2개 확인 (data/sheets/):
  - 리플레이 코드: 2024~2026, KR/JP/PAC, 열: 대회/지역/연도/단계/일/매치#/게임#/팀A/팀B/코드
  - 선수 방송/디스코드: 팀별 블록, 열마다 선수 2명, 행: 이름(역할) / Soop / 치지직 / Discord, 유튜브 열 별도. (26.09.15 스테3 로스터 기준, "자유배포 가능" 표기)
- gh(GitHub CLI) 설치 완료: C:\Program Files\GitHub CLI\gh.exe. 로그인은 사용자가 직접 해야 함.

## 완료 (2026-10-11)
- 대회 페이지 44개 수집, 원본 761경기 -> 날짜 파싱 수정 후 중복 제거 706경기, 한국팀 포함 592경기
- 정규시즌 36경기 일치 확인 (2025 S1~S3, 2026 S1~S3)
- 팀 이름 정규화: data/aliases.json (직접 수정 가능)
- 빌드: `node collector/build.mjs` -> data/site/{matches,team-stats,potm}.json
- 교차 검증: owtics 10/9 SEIJI 0-3 ZETA 경기가 Liquipedia 값과 같은지 확인함 (아래 결과 참고)

## 알려진 문제
- 날짜 없는 경기 40개 (대진 미정 브래킷 추정) - 확인 필요
- 한국팀 판별이 "한국 대회 페이지에 나온 팀"이라 외국팀이 섞임 (예: From The Gamer). 팀 지역표 필요.
- Open Qualifier 페이지 경기는 진행 0으로 나옴 (형식이 다름). 우선순위 낮음.
- POTM은 선수 이름 문자열(Liquipedia mvp). 선수 ID와 연결 필요 (선수 시트와 매칭).
