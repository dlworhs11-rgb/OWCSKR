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
