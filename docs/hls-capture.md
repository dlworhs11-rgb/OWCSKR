# OBS 없이 프레임 받기 (SOOP HLS)

서버(특히 ARM)에서는 OBS 브라우저 소스를 믿을 수 없다(OPS-05, OCR-11). 그래서 방송 HLS를 `ffmpeg`로 직접 디코딩한다(P1-17).

| 파일 | 하는 일 |
|---|---|
| `tools/frames.py` | `resolve_hls()`: yt-dlp로 HLS 주소와 헤더를 받는다. `HlsFrames`: ffmpeg 한 개로 interval마다 한 장씩 받고, 끊기면 스스로 복구한다. `normalize()`: 검은 띠를 잘라 정확히 1920x1080 BGR로 맞춘다. `StableCrop`: 스트림용 `normalize()`(오래 이어지는 띠만 자름). `HlsSource`: `live_capture`의 프레임 원천 인터페이스(`ObsSource`와 같은 메서드). |
| `tools/screen_match.py` | `locate()`, `classify_gamedata()`: ±16px 탐색 템플릿 매칭. 찾은 오프셋(960 기준)을 돌려준다. |
| `tools/frames_probe.py` | 경기일 점검용. 포맷 목록(비로그인 화질)을 출력하고 프레임 몇 장을 저장한다. |

## 준비
- `ffmpeg`, `yt-dlp`가 PATH에 있어야 한다. 다른 경로면 `FFMPEG_CMD`, `YTDLP_CMD` 환경 변수로 지정한다.
- yt-dlp는 SOOP 추출기가 자주 바뀌므로 버전을 고정하고 정기적으로 올린다.
- yt-dlp SOOP 라이브 추출기는 `https://play.sooplive.com/<채널>`로 시작하는 주소를 받는다. `/embed?autoPlay=...`도 받지만 그 주소를 그대로 Referer로 보내므로 `channel_page()`가 재생 페이지 주소로 바꾼다. 추출기가 Referer를 넣어 주지 않으면 `resolve_hls()`가 `https://play.sooplive.com/`을 넣는다.

## 경기일 첫 확인
```bash
yt-dlp -F https://play.sooplive.com/owesports          # 비로그인으로 받을 수 있는 화질
python -I tools/frames_probe.py --count 3              # data/live/probe/<시각>/raw_N.png, norm_N.png
python -I tools/frames_probe.py --count 5 --interval 1 --keyframes-only   # 출력된 프레임 시각 간격 = 키프레임 간격
```
표 숫자가 검증을 통과하려면 720p 이상이 필요할 가능성이 크다. 540p만 나오면 사전 재구축 전에 쿠키/로그인 경로를 먼저 본다.

## 설계
- **크기 고정 후 정규화.** rawvideo는 프레임 크기가 고정이어야 stdout을 정확히 자를 수 있다. 그래서 ffmpeg가 `scale=1920:1080:force_original_aspect_ratio=decrease` + `pad`로 항상 1920x1080을 낸다. 늘리지 않고 검게 채우므로, 원천 비율이 16:9가 아니거나 원천에 띠가 있어도 `normalize()`가 띠로 보고 잘라 낼 수 있다(늘린 뒤에는 되돌릴 수 없다). 광고나 ABR로 해상도가 중간에 바뀌어도 바이트 단위가 어긋나지 않는다. 16:9 원천이면 bicubic 한 번이고 `normalize()`는 그대로 돌려준다.
- **검은 띠 판정은 보수적이다.** 가장자리에서 이어지는, 어둡고(평균 < 20, TV 범위 검정 16 포함) 균일한(표준편차 < 4) 줄만 띠로 본다. 1% 미만이거나 절반 넘게 잘라야 하면 무시한다. 양쪽 띠 두께가 1%(최소 2px) 넘게 다르면 띠가 아니라 내용으로 본다(ffmpeg `pad`와 원천의 레터박스는 가운데 정렬이다). 잘라 낸 결과가 16:9(±3%)일 때만 자른다. 방송 자체는 언제나 16:9이므로 어두운 장면이나 페이드는 잘리지 않고 `info['warn']`만 남는다.
- **한 장으로는 구분할 수 없는 경우.** 검은 화면 가운데 놓인 16:9 그림(리플레이 창, 광고)은 한 장만 보면 띠와 똑같아서 `normalize()`가 잘라 확대한다. 스트림에서는 `StableCrop`을 쓴다. 새 잘라내기는 같은 상자(±4px)가 3장 연속 나와야 적용되고, 처음에는 자르지 않는다. `HlsSource`가 이것을 쓴다.
- **복구.** ffmpeg 종료, 3×interval 동안 프레임 없음(첫 프레임은 시작 후 20초 유예 + 3×interval까지 기다린다), stderr의 HTTP 403 중 하나면 ffmpeg를 죽이고 URL을 다시 받아 재시작한다. ffmpeg는 4xx를 warning 수준으로 찍고 종료 코드 0으로 끝나므로 `-loglevel warning`으로 돌린다(stderr는 계속 읽어 비우고 마지막 20줄만 둔다). 대기는 2, 4, 8 … 60초. 한 번에 60초 넘게 정상으로 받으면 연속 실패 수를 0으로 되돌린다. `kick()`은 백오프 없이 바로 다시 받는다(실패로 세지 않음). `HlsFrames.grab()`은 이런 일로 예외를 내지 않고 `None`을 돌려준다. `HlsSource.grab()`은 반대로 예외를 낸다(`live_capture`의 `Grabber`가 예외로 실패를 세고 재시작·알림을 하기 때문). `close()`(with 블록 종료, 예외, Ctrl+C 포함)와 인터프리터 종료 시 ffmpeg를 죽인다.
- **CPU.** 기본은 모든 프레임을 디코딩한다(1080p60 20초에 x86 데스크톱 CPU 4.1초, 2 OCPU ARM에서는 더 무겁다). `keyframes_only=True`(`-skip_frame nokey`)면 키프레임만 디코딩해 0.06초다. 프레임 시각이 키프레임 간격(보통 1~2초)에 맞춰지므로, 경기일에 `--keyframes-only` 점검으로 간격을 본 뒤 켠다.
- **간격.** `live_capture`는 POTM 직후 2초마다 프레임을 찾는다. 그래서 `HlsSource` 기본 interval은 2초이고, `grab()`은 지난번보다 새 프레임을 interval만큼 기다렸다가 돌려준다.
- **오프셋.** `classify_gamedata()`가 돌려주는 `(dx, dy)`는 960x540 기준이다. 1920x1080 좌표에는 2를 곱해 쓴다.

## live_capture에서 쓰기
```bash
OWCSKR_FRAME_SOURCE=hls python -I tools/live_capture.py --until 2026-10-25T23:30:00+09:00   # 또는 --source hls
```
| 설정 | 기본값 | 뜻 |
|---|---|---|
| `--source` / `OWCSKR_FRAME_SOURCE` | `obs` | `obs`: OBS 브라우저 소스 스크린샷, `hls`: `frames.HlsSource`. 대소문자 무관. `OWCSKR_FRAME_SOURCE`가 다른 값이면 경고를 남기고 `obs`(`platform_util.frame_source`, `run_live.sh`·점검 스크립트도 같음), `--source`가 다른 값이면 exit 2 |
| `--url` / `OWCSKR_HLS_CHANNEL` | `owesports` | hls일 때 채널(또는 재생 페이지 주소). obs일 때 `--url`은 플레이어 페이지 |
| `OWCSKR_HLS_KEYFRAMES` | (없음) | `1`이면 `keyframes_only=True` |

- 자가 점검(`selfcheck.py --source hls`)은 hls일 때 `ffmpeg`, `yt-dlp`(`FFMPEG_CMD`, `YTDLP_CMD` 또는 PATH)가 없으면 fatal이다. obs일 때는 경고만 낸다.
- GAME DATA 판정은 두 원천 모두 `classify_gamedata()`(±16px)다. 점수는 탐색 범위에 오프셋 0이 들어 있어 옛 판정보다 낮아지지 않는다. 오프셋이 0이 아니면 저장 전에 1080p 프레임을 −오프셋×2만큼 옮겨 OCR 고정 좌표에 맞추고 로그에 남긴다. 0이면 그대로 저장한다.
- 방송이 끝나면 HLS는 정지 화면이 아니라 `grab()` 예외가 된다. 그 'no frame' 알림(`frames-down`)과 정지·검은 화면 알림·새로고침은 방송 시간 안에서만 낸다(오늘 일정 + 미정 플레이오프 경기, 마지막 경기 예상 종료 또는 마지막 POTM 카드까지). 재시작 복구는 계속한다.

## 아직 할 일 (P1-17 5~7)
- 밴/POTM 화면: `screen_kind`는 이미 `locate()`(±12px)로 찾지만, 찾은 오프셋을 그 화면의 판독 칸 좌표에 아직 반영하지 않는다.
- 새 원천 프레임으로 기준 이미지와 사전을 다시 만들기.
- 제목 문턱 0.6은 오프셋 0에서도 약하다(합성 시험: `GAME DATA` 기준에 `GAME 3`이 0.83). ±16px 탐색은 점수를 올리기만 하므로 다른 제목 화면이 문턱을 넘을 수 있다(`MAP DATA` 0.23 → 0.56). 새 기준 이미지로 실제 비-GAME DATA 화면 점수를 재서 문턱을 다시 정한다.
