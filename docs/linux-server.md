# 리눅스 서버에서 돌리기 (Oracle Cloud 등)

윈도우 PC와 같은 코드가 리눅스에서도 돈다. 차이는 `tools/platform_util.py` 한 곳에 모았다.

| 윈도우 | 리눅스 |
|---|---|
| 작업 스케줄러 `OWCSKR\Daily`, `OWCSKR\LiveCapture_<날짜>` | systemd 사용자 타이머 `owcskr-daily`, `owcskr-live-<날짜>` |
| `tools/*.bat`, `register_tasks.ps1` | `tools/*.sh` (`register_tasks.sh`, `run_daily.sh`, `run_live.sh`, `start_watchers.sh`) |
| 메시지 창 (`popup`) | 디스코드 웹훅 (`OWCSKR_DISCORD_WEBHOOK`), 없으면 로그만 |
| `%APPDATA%\obs-studio` | `~/.config/obs-studio` |
| `gh auth login` | `.env`의 `GH_TOKEN` |

## 처음 설치 (Ubuntu 22.04/24.04, ARM 또는 x86)
```bash
sudo timedatectl set-timezone Asia/Seoul          # 날짜 계산(date.today)이 한국 날짜와 맞도록
sudo apt update
sudo apt install -y git python3-venv nodejs tesseract-ocr ffmpeg gh
# OBS 방식 캡처를 쓸 때만: sudo apt install -y obs-studio xvfb
git clone https://github.com/dlworhs11-rgb/OWCSKR.git && cd OWCSKR
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env                  # GH_TOKEN, OWCSKR_DISCORD_WEBHOOK, ...
bash tools/register_tasks.sh                       # 매일 09:00 KST 작업 등록 + 한 번 실행
```
- Node는 18 이상이 필요하다 (`fetch` 사용). 배포판 기본 버전이 낮으면 NodeSource 등으로 설치한다.
- `register_tasks.sh`가 `loginctl enable-linger`를 켠다. 실패하면 `sudo loginctl enable-linger $USER`를 한 번 실행한다. 이게 꺼져 있으면 로그아웃했을 때 타이머가 돌지 않는다.

## 서버로 따로 옮겨야 하는 것 (저장소에 없음)
저작권이나 비공개 문제로 git에 없는 파일들이다. 기존 PC에서 `scp`/`rsync`로 같은 경로에 복사한다.
- `data/vod/` 중 학습/기준 이미지: `maps/m_3480.png`, `maps/m_9465.png`, `hi_3466.png`, `maps/m_*.png`, `p1a/frames/m0*_totals_*.png` (`live_capture.py`, `ocr_run.py`가 시작할 때 읽음)
- `data/name_lib/`, `data/header_lib/`, `data/digit_lib/`, `data/ref/`
- 사이트 기록기 폴더 (`score_watch.py` 등) → `.env`의 `OWCSKR_SITE_DIR`

## 확인
```bash
.venv/bin/python -I tools/schedule_today.py --upcoming --dry    # 앞으로 14일 경기일과 캡처 시간
systemctl --user list-timers 'owcskr-*'                          # 등록된 타이머
tail -f data/live/daily.log data/live/task.log
.venv/bin/python -m pytest tests
```
해제: `bash tools/unregister_tasks.sh`

## 아직 남은 일
- OBS 없이 프레임 받기 (SOOP HLS → ffmpeg 또는 헤드리스 브라우저). 지금 `run_live.sh`는 OBS를 가상 화면(xvfb)에서 띄운다.
- 사이트 기록기(`score_watch.py` 등)도 OBS에서 화면을 받으므로 같이 바꿔야 한다.
