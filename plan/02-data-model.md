# 02. 데이터 모델 (확정)

## 원본 (사람이 고치는 곳): 구글 시트 / data/manual/*.json
- teams: name, abbr, 디스코드, 방송(치지직/SOOP), 로고
- players: handle, 현재팀, 역할, 치지직/SOOP/디스코드
- overrides: Liquipedia 값이 틀릴 때 덮어쓰는 값 (예: POTM 수정)

## 수집 결과 (자동): data/lp/*.json
- match: competition, date(ISO, KST +09:00), bestof, team1, team2, score1, score2, winner(1/2/0/null),
  played, maps[{map, mode, score1, score2, winner, bans{t1,t2}}], potm, broadcast{afreeca/chzzk/...}, vod, casters[]
- 승패/세트 점수는 맵 승리 수로 직접 계산 (위키 값과 대조)

## 계산 결과: data/site/*.json
- standings(대회별), team stats(승률, 맵 승률), player potm 횟수, 라이브 상태 대상 목록

## 키
- 팀은 Liquipedia 팀 이름을 정규화한 slug (예: zeta-division). 별칭표(aliases)로 "ZANSIDE Gaming"=="ZANSIDE GAMING" 처리.
