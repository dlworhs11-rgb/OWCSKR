# OWCSKR

한국 오버워치 챔피언스 시리즈(OWCS) 결과·통계·방송 허브. (개발 중)

## 현재 상태
- 홈페이지: 없음 (새로 만들 예정). 데이터 수집과 실시간 업로드만 동작
- 경기 결과·일정·밴·POTM: Liquipedia API (`collector/`)
- 선수 스탯·밴·세트 승패·POTM 실시간: 공식 중계 화면을 OBS로 캡처해서 읽음 (`tools/`, 설명 `docs/vod-stats.md`)
- 실시간 결과는 맵마다 `data/manual/mapstats/<날짜>.json`으로 바로 올라감

## 데이터 출처
- 경기 데이터: [Liquipedia](https://liquipedia.net/overwatch/) (CC-BY-SA 3.0), MediaWiki API 사용. HTML 크롤링 없음.
- 선수 스탯·밴·POTM: OWCS 공식 중계(SOOP owesports) 화면
- 선수 방송/디스코드, 리플레이 코드: 커뮤니티 공유 시트

Not affiliated with Blizzard Entertainment. Overwatch is a trademark of Blizzard Entertainment, Inc.

## 개발
```bash
node collector/run-lp.mjs   # Liquipedia 수집 (2.2초 간격, 캐시 사용)
node collector/build.mjs    # 정규화/집계 -> data/site/*.json (새 홈페이지가 쓸 데이터)
python -I tools/live_capture.py --hours 6   # 방송 캡처 (보통은 예약 작업이 실행)
```
계획 문서: `plan/`, 실시간 캡처 설명: `docs/vod-stats.md`
