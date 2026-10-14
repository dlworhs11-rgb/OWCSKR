# 방송 화면에서 선수 통계 읽기 (VOD GAME DATA)

공식 중계의 맵 종료 화면("GAME DATA")에서 선수별 E/A/D/피해/힐/경감을 읽는 방법. 영상 자체는 저장·배포하지 않고 숫자만 쓴다.

## 순서
1. `tools/vod_pipeline.py PART START END TAG` : 15초 간격으로 스캔 -> "GAME DATA" 제목을 이미지 비교로 탐지 -> 표/합계 화면 구분 -> 1080p 캡처
2. `tools/ocr_run.py OUT.json DIR...` : 숫자 글자 모양 비교로 표를 읽고, **팀 합계 화면의 합과 대조**해서 검증 (E, D, 피해, 힐, 경감)
3. `tools/ocr_names.py` : 선수 이름 글자 모양을 알려진 이름과 비교, 모르는 이름만 사람이 확인
4. 결과를 `data/manual/mapstats/YYYY-MM-DD.json` 에 저장 -> `node collector/build.mjs` 가 경기에 연결

## 검증 결과 (2026-10-11, Week 2 Day 3, 12개 맵)
- 맵 탐지: 12/12 (실제 맵 수와 동일)
- 숫자 글자 오류: 1,087글자 중 1 (정답 맵을 하나씩 빼고 학습한 시험)
- 선수 이름: 70/70, 합계 화면 숫자: 269글자 오류 0
- 새로 읽은 5개 맵은 모두 합계 화면과 일치

## 한계
- 맵 시간(M:SS) 자동 읽기는 샘플이 적어 불안정 -> 지금은 사람이 확인한 값 사용
- 어시스트(A)는 합계 화면에 없어 별도 검증 없음
- 방송 디자인이 바뀌면 칸 위치/기준 화면을 다시 맞춰야 함
- 학습용 정답 캡처(`data/vod/`)는 저작권 때문에 저장소에 없음. 새 환경에서는 정답 맵 몇 개를 다시 만들어야 함

## 데이터 형태 (`matches.json` 의 `mapStats`)
`m.mapStats = [{ game, map, mapTime, teams: { "팀명": [{ name, e, a, d, dmg, heal, mit }] }, reading, verified }]`
- E = Eliminations (어시스트 기여 포함), `reading` = manual | ocr, `verified` = 합계 화면과 일치 여부

## 라이브 자동 캡처 (OBS)
영상을 내려받지 않고, OBS 브라우저 소스로 SOOP 공식 임베드 플레이어(`/embed?autoPlay=true&mutePlay=true`)를 평소처럼 재생하면서(광고 포함, 화면에 표시 안 됨) 10초마다 그 이미지 1장만 받아 처리한다.

- `tools/live_capture.py` : OBS 실행 -> 10초마다 캡처 -> GAME DATA가 아닌 화면은 즉시 버림 -> 맵마다 표 3장 + 합계 1장 저장 -> `ocr_run.py` -> 끝나면 `assemble_day.py`
- `tools/assemble_day.py` : 이름 사전(`data/name_lib/`)으로 선수 이름, 선수 시트로 팀, Liquipedia 일정으로 경기/세트/맵 결정 -> `data/live/<날짜>/mapstats.json`
  (모르는 이름은 `data/live/<날짜>/unknown/`에 저장, 사람이 확인 후 `data/name_lib/<이름>__<태그>.png`로 넣고 다시 실행)
- `tools/schedule_today.py` : 그날 한국 리그 첫 경기 20분 전에 `OWCSKR\LiveCapture` 작업 예약
- 바탕화면 `OWCSKR_예약등록.bat` : 매일 09:00 `OWCSKR\Daily` 작업 등록 (Liquipedia 갱신 -> 빌드 -> 당일 예약). 해제는 `OWCSKR_예약해제.bat`
- 사용자의 OBS 장면은 건드리지 않는다: 전용 장면 모음 `OWCSKR` 사용, 다른 장면 모음으로 OBS가 켜져 있으면 캡처하지 않고 종료

### 끝까지 시험 (2026-10-14)
다시보기 1경기 1세트 구간으로 `live_capture.py` 실행 -> 통계 화면 탐지(점수 0.996), 숫자 60칸, 이름 10명, 팀, 경기/세트/맵(O2 Blast vs ZANSIDE G1 Nepal)까지 손으로 확인한 정답과 전부 일치.
아직 실제 라이브에서는 돌려 보지 않았다.
