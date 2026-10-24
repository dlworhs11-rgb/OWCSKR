# OWCSKR

한국 오버워치 챔피언스 시리즈(OWCS) 결과·통계·방송 허브. (개발 중)

## 현재 상태
- 이 저장소는 데이터 수집과 실시간 업로드만 한다. 사이트(owticker.com)는 따로 있는 `owcs-kr` 저장소가 이 저장소의 `data/`를 받아 빌드한다
- 경기 결과·일정·밴·POTM: Liquipedia API (`collector/`)
- 선수 스탯·밴·세트 승패·POTM 실시간: 공식 중계 화면을 OBS 또는 SOOP HLS(`docs/hls-capture.md`)로 받아 읽음 (`tools/`, 설명 `docs/vod-stats.md`)
- 실시간 결과는 맵마다 `data/manual/mapstats/<날짜>.json`으로 바로 올라감 (사이트에는 다음 사이트 빌드 때 반영)

## 데이터 출처
- 경기 데이터: [Liquipedia](https://liquipedia.net/overwatch/) (CC-BY-SA 3.0), MediaWiki API 사용. HTML 크롤링 없음.
- 선수 스탯·밴·POTM: OWCS 공식 중계(SOOP owesports) 화면
- 선수 방송/디스코드, 리플레이 코드: 커뮤니티 공유 시트

Not affiliated with Blizzard Entertainment. Overwatch is a trademark of Blizzard Entertainment, Inc.

## 개발
```bash
node collector/run-lp.mjs   # Liquipedia 수집 (2.2초 간격, 캐시 사용)
node collector/build.mjs    # 정규화/집계 -> data/site/*.json (사이트 빌드가 읽는 데이터)
python -I tools/live_capture.py --hours 6   # 방송 캡처 (보통은 예약 작업이 실행)
npm test                    # collector 시험 (Node 20 이상)
python -m pytest tests -q   # tools 시험
```
계획 문서: `plan/`, 실시간 캡처 설명: `docs/vod-stats.md`, 리눅스 서버 설치: `docs/linux-server.md`

윈도우는 `tools/*.bat`(작업 스케줄러), 리눅스는 `tools/*.sh`(systemd 사용자 타이머)로 같은 작업을 돌린다.
설정은 환경변수(`.env.example` 참고)로 받는다.
