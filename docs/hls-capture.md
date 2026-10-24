# OBS 없이 프레임 받기 (SOOP HLS)

서버(특히 ARM)에서는 OBS 브라우저 소스를 믿을 수 없다(OPS-05, OCR-11). 그래서 방송 HLS를 `ffmpeg`로 직접 디코딩한다(P1-17).

| 파일 | 하는 일 |
|---|---|
| `tools/frames.py` | `resolve_hls()`: yt-dlp로 HLS 주소와 헤더를 받는다. `HlsFrames`: ffmpeg 한 개로 interval마다 한 장씩 받고, 끊기면 스스로 복구한다. `normalize()`: 검은 띠를 잘라 정확히 1920x1080 BGR로 맞춘다. |
| `tools/screen_match.py` | `locate()`, `classify_gamedata()`: ±16px 탐색 템플릿 매칭. 찾은 오프셋(960 기준)을 돌려준다. |
| `tools/frames_probe.py` | 경기일 점검용. 포맷 목록(비로그인 화질)을 출력하고 프레임 몇 장을 저장한다. |

## 준비
- `ffmpeg`, `yt-dlp`가 PATH에 있어야 한다. 다른 경로면 `FFMPEG_CMD`, `YTDLP_CMD` 환경 변수로 지정한다.
- yt-dlp는 SOOP 추출기가 자주 바뀌므로 버전을 고정하고 정기적으로 올린다.
- yt-dlp SOOP 라이브 추출기는 `https://play.sooplive.com/<채널>` 주소만 받는다(`/embed`는 안 됨). HLS 요청에는 `Referer: https://play.sooplive.com/`가 필요해서 `resolve_hls()`가 없으면 넣는다.

## 경기일 첫 확인
```bash
yt-dlp -F https://play.sooplive.com/owesports          # 비로그인으로 받을 수 있는 화질
python -I tools/frames_probe.py --count 3              # data/live/probe/<시각>/raw_N.png, norm_N.png
```
표 숫자가 검증을 통과하려면 720p 이상이 필요할 가능성이 크다. 540p만 나오면 사전 재구축 전에 쿠키/로그인 경로를 먼저 본다.

## 설계
- **크기 고정 후 정규화.** rawvideo는 프레임 크기가 고정이어야 stdout을 정확히 자를 수 있다. 그래서 ffmpeg가 `scale=1920:1080:force_original_aspect_ratio=decrease` + `pad`로 항상 1920x1080을 낸다. 늘리지 않고 검게 채우므로, 원천 비율이 16:9가 아니거나 원천에 띠가 있어도 `normalize()`가 띠로 보고 잘라 낼 수 있다(늘린 뒤에는 되돌릴 수 없다). 광고나 ABR로 해상도가 중간에 바뀌어도 바이트 단위가 어긋나지 않는다. 16:9 원천이면 bicubic 한 번이고 `normalize()`는 그대로 돌려준다.
- **검은 띠 판정은 보수적이다.** 가장자리에서 이어지는, 어둡고(평균 < 20, TV 범위 검정 16 포함) 균일한(표준편차 < 4) 줄만 띠로 본다. 1% 미만이거나 절반 넘게 잘라야 하면 무시한다. 잘라 낸 결과가 16:9(±3%)일 때만 자른다. 방송 자체는 언제나 16:9이므로 어두운 장면이나 페이드는 잘리지 않고 `info['warn']`만 남는다.
- **복구.** ffmpeg 종료, 3×interval 동안 프레임 없음(시작 직후에는 20초 유예), stderr의 HTTP 403 중 하나면 ffmpeg를 죽이고 URL을 다시 받아 재시작한다. 대기는 2, 4, 8 … 60초. 한 번에 60초 넘게 정상으로 받으면 연속 실패 수를 0으로 되돌린다. `grab()`은 이런 일로 예외를 내지 않고 `None`을 돌려준다. `close()`(with 블록 종료, 예외, Ctrl+C 포함)와 인터프리터 종료 시 ffmpeg를 죽인다.
- **오프셋.** `classify_gamedata()`가 돌려주는 `(dx, dy)`는 960x540 기준이다. 1920x1080 좌표에는 2를 곱해 쓴다.

## 아직 할 일 (P1-17 4~7)
- `live_capture.py`에 연결: OBS 스크린샷 대신 `HlsFrames.grab()` → `normalize()` → `classify_gamedata()`.
- `screen_kind`(밴/POTM)에도 `locate()` 적용, 찾은 오프셋을 OCR 좌표에 반영.
- 새 원천 프레임으로 기준 이미지와 사전을 다시 만들기.
