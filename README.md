# OWCSKR

한국 오버워치 챔피언스 시리즈(OWCS) 결과·통계·방송 허브. (개발 중)

## 기능 (계획)
- 대회 결과 / 순위 / 일정
- 팀·선수별 승률, POTM 횟수 (세부 스탯 K/D·딜량은 2차)
- 선수 방송(치지직·SOOP) 및 디스코드 주소, 라이브 여부

## 데이터 출처
- 경기 데이터: [Liquipedia](https://liquipedia.net/overwatch/) (CC-BY-SA 3.0), MediaWiki API 사용. HTML 크롤링 없음.
- 선수 방송/디스코드: 커뮤니티 공유 시트 (자유배포 표기)
- 리플레이 코드: 커뮤니티 공유 시트

Not affiliated with Blizzard Entertainment. Overwatch is a trademark of Blizzard Entertainment, Inc.

## 개발
```bash
node collector/run-lp.mjs   # Liquipedia 수집 (2.2초 간격, 캐시 사용)
node collector/build.mjs    # 정규화/집계 -> data/site/*.json
```
계획 문서: `plan/`
