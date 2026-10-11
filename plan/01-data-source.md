# 01. 데이터 출처

## 결정 (사용자)
- 공개 출처 + owtics 직접 수집을 둘 다 사용.

## owtics에서 얻는 것
- 대회/순위/경기/맵 결과/영웅 밴/POTM/선수 맵별 스탯/로스터
- 선수 소셜 링크 (플랫폼: CHZZK, DISCORD 등), 대회 방송 채널 목록

## 할 일
- [ ] robots.txt 재확인: 일반 크롤러 허용, AI 학습/SEO 봇 차단. 우리는 학습용이 아님.
- [ ] 이용약관 전문 읽기 (자동 수집 조항 확인) - 지금은 못 찾음
- [ ] owtics 디스코드로 사용 허락 문의 (공개 공유 전 필수 권장)
- [ ] Liquipedia MediaWiki API 시험 (UA 명시, 2초에 1요청, parse는 30초에 1요청). HTML 긁기 금지. LiquipediaDB는 승인 필요.
- [ ] 출처 표기 문구 정하기 ("데이터 출처: owtics.gg")

## 수집 규칙 (지킬 것)
- 1.5초에 1요청 이하, 식별 가능한 User-Agent
- 완료된 경기는 한 번만 받고 영구 캐시
- 원본 JSON 통째 재배포 금지. 가공한 통계 + 출처 표기

## 검증 결과 (2026-10-11)
- Liquipedia MediaWiki API 동작함: `https://liquipedia.net/overwatch/api.php` (UA 명시, 2초 간격)
- 페이지 이름 규칙: `Overwatch Champions Series/2026/Asia/Stage 3/Korea/Regular Season`
  (팀 페이지의 링크 목록 `prop=links`에서 대회 페이지 이름을 찾을 수 있음)
- 원문(wikitext)에 들어있는 것: 순위표, 라운드 로빈 표, 경기 일정/날짜, 세트 스코어(맵/모드/점수),
  영웅 밴, 중계 채널(`afreeca=owesports` 등), 해설자, VOD 칸
- 없는 것: 선수 개인 스탯, POTM (-> 2차 / 직접 입력)
- 과거 시즌: Contenders 2020~2023, OWCS 2024~2026 페이지가 있음
