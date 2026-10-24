# 리눅스 서버에서 돌리기 (Oracle Cloud 등)

윈도우 PC와 같은 코드가 리눅스에서도 돈다. 차이는 `tools/platform_util.py` 한 곳에 모았다.

| 윈도우 | 리눅스 |
|---|---|
| 작업 스케줄러 `OWCSKR\Daily` | systemd 사용자 타이머 `owcskr-daily` (09:00 KST + 부팅 3분 뒤) |
| `OWCSKR\LiveCapture_<날짜>` | `owcskr-live-<날짜>` (타이머 + 서비스, 죽으면 다시 시작) |
| `OWCSKR\MatchdayCheck_<날짜>`, `SoopQuality_<날짜>`, `Freshness_<날짜>` | `owcskr-check-<날짜>`, `owcskr-soop-<날짜>`, `owcskr-fresh-<날짜>` |
| `tools/*.bat`, `register_tasks.ps1` | `tools/*.sh` (`register_tasks.sh`, `run_daily.sh`, `run_live.sh`, `start_watchers.sh`) |
| 메시지 창 (`popup`) | 디스코드 웹훅 (`OWCSKR_DISCORD_WEBHOOK`), 없으면 로그만 |
| `%APPDATA%\obs-studio` | `~/.config/obs-studio` |
| `gh auth login` | `.env`의 `GH_TOKEN` (+ `gh auth setup-git`) |

## 시작 전에 확인할 것
- **OBS 방식 캡처는 ARM에서 확인되지 않았다.** Ubuntu의 apt `obs-studio`에는 브라우저 소스(CEF)가 빠져 있을 가능성이 크고, 공식 OBS PPA는 amd64만 있다. ARM VM에서 아래를 먼저 해 본다.
  ```bash
  xvfb-run -a .venv/bin/python -I tools/obs_setup.py start 'https://vod.sooplive.com/player/209539901?change_second=3440'
  .venv/bin/python -I tools/obs_snap.py 6 10      # data/live/snap_report.txt에 실제 화면이 찍혔는지
  ```
  검은 화면이거나 `CreateInput`이 실패하면 OBS 경로는 포기하고, OBS 없이 SOOP HLS를 `yt-dlp` + `ffmpeg`로 받는 프레임 입구(P1-17, `tools/frames.py`)가 끝난 다음에 옮긴다. 사이트 기록기(`score_watch.py` 등)도 OBS 화면을 읽으므로 같이 바꿔야 한다.
- **Oracle Always Free는 유휴 인스턴스를 회수한다** (7일 동안 CPU·네트워크·메모리 사용이 낮으면). 경기 없는 주에는 일일 작업 몇 분뿐이라 회수 대상이 된다. 계정을 **PAYG(종량제)로 올린다**: Always Free 한도 안에서는 요금이 없고 회수 대상에서 빠진다. 부하를 일부러 만드는 방법은 쓰지 않는다. 회수돼도 알 수 있게 아래 healthchecks를 꼭 설정한다.

## 처음 설치 (Ubuntu 22.04/24.04, ARM 또는 x86)
전용 계정(예: `owcskr`, sudo 없음)으로 돌리는 것을 권한다. 설치 명령 중 `sudo`는 관리자 계정에서 한다.
```bash
sudo timedatectl set-timezone Asia/Seoul          # 날짜 계산(date.today)이 한국 날짜와 맞도록
sudo apt update
sudo apt install -y git python3-venv tesseract-ocr ffmpeg gh curl dbus-user-session
# Node: 배포판 nodejs는 22.04에서 12.x라 못 쓴다 (collector는 fetch 때문에 18 이상 필요). NodeSource 20.x:
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version                                     # v20.x 인지 확인
# OBS 방식 캡처를 쓸 때만 (위 "시작 전에" 확인 후): sudo apt install -y obs-studio xvfb
```
그다음 **그 계정으로 직접 ssh 접속해서** (`ssh owcskr@서버`, `sudo -u`/`su` 아님):
```bash
git clone https://github.com/dlworhs11-rgb/OWCSKR.git && cd OWCSKR
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env && nano .env   # GH_TOKEN, OWCSKR_DISCORD_WEBHOOK, OWCSKR_HC_* ...
gh auth setup-git                                  # git push도 GH_TOKEN을 쓰게 (OWCSKR_AUTOPUSH=1일 때)
git config user.name 'OWCSKR server' && git config user.email '<메일>'   # OWCSKR_AUTOCOMMIT=1일 때
bash tools/register_tasks.sh                       # 매일 09:00 KST + 부팅 3분 뒤 작업 등록, 한 번 실행
```
- **python은 venv만 지원한다** (`.venv/bin/python`). 시스템 python(`OWCSKR_PYTHON=python3`)은 `-I`가 user site를 막아서 `pip install --user` 패키지가 안 보이고, 24.04는 PEP 668 때문에 시스템 pip 설치 자체가 막힌다.
- **nvm으로 Node를 깔면 안 된다.** systemd 사용자 타이머의 PATH(`/usr/local/bin:/usr/bin:...`)에는 nvm 경로가 없어서, 손으로 돌리면 되는데 타이머에서만 `node: command not found`가 된다. `register_tasks.sh`가 이 경우 경고한다.
- **`register_tasks.sh`는 그 계정으로 직접 로그인한 셸에서 실행한다.** `systemctl --user`/`systemd-run --user`는 사용자 버스가 필요한데, `sudo -u`/`su`로 들어간 셸에는 `XDG_RUNTIME_DIR`이 없어 `Failed to connect to bus`로 멈춘다. 최소 이미지에는 `dbus-user-session`이 없을 수 있다 (위 apt 명령에 포함, 설치 후 다시 로그인).
- `register_tasks.sh`가 `loginctl enable-linger`를 켠다. 실패하면 관리자 계정에서 `sudo loginctl enable-linger owcskr`를 한 번 실행한다. 이게 꺼져 있으면 로그아웃했을 때 타이머가 돌지 않는다.

## `.env` 형식
`tools/env.sh`는 `.env`를 셸 코드로 실행하지 않고 `KEY=VALUE` 줄로 읽는다. 같은 파일을 systemd 유닛이 `EnvironmentFile=`로 읽으므로 두 쪽이 같은 값을 얻는 형식만 받는다 (`.env.example` 머리말).
- 공백이 들어간 값은 따옴표로 감싼다: `OWCSKR_SITE_DIR="/home/owcskr/OWCS KR Home"`.
- `#`로 시작하는 줄과 빈 줄은 무시. 백슬래시, `$변수`, `export`, `=` 앞뒤 공백은 쓰지 않는다.
- 윈도우에서 편집했으면 `dos2unix .env` (CRLF면 모든 작업이 오류로 멈춘다).
- `OWCSKR_SITE_DIR`를 적었는데 그 폴더가 없으면 오류로 알린다 (비워 두면 "이 기계에는 기록기 없음").

## 어떻게 도는가
- `owcskr-daily.timer`: 매일 09:00 KST와 **부팅 3분 뒤**(`OnStartupSec=3min`)에 `run_daily.sh`를 돌린다. 경기일 타이머는 메모리에만 있는(transient) 유닛이라 재부팅하면 사라지는데, 부팅 때 다시 만든다. 이미 시작 시각이 지났고 끝나기 전이면 바로 시작한다.
- `run_daily.sh` 순서: (캡처가 안 돌고 작업 트리가 깨끗하면) `git pull --ff-only` → `run-lp.mjs --discover` (`competitions.json`/`active.json`이 바뀌면 `OWCSKR_AUTOCOMMIT=1`일 때 커밋, `OWCSKR_AUTOPUSH=1`일 때 push) → `run-lp.mjs --active-only` → `build.mjs` → `republish_recent.py` → `schedule_today.py --upcoming` → 백업 → 다시보기 댓글 → 사이트 최신성 점검. 단계가 실패해도 다음 단계를 돌리고, 끝에서 실패 목록과 출력 끝부분을 한 번에 알린다. 실패가 있으면 종료 코드 1 (`run-lp` 종료 코드 2 = 일부 페이지 실패, git pull/push 실패, 최신성 점검은 경고: 알리기만 한다).
- `owcskr-live-<날짜>`: `run_live.sh HOURS DATE`. 처음 시작할 때 끝나는 시각(지금 + HOURS)을 `data/live/<날짜>/until.txt`에 적고 `live_capture.py --until`로 넘긴다. 죽으면 60초 뒤 다시 시작하고(`Restart=on-failure`), 다시 시작해도 같은 시각에 끝난다. `live_capture.py` 시작 점검 실패(종료 코드 2)는 다시 시작하지 않는다. 같은 날 두 번 뜨지 않게 `flock`으로 잠근다. `RuntimeMaxSec`는 일정 길이 + 1시간(안전장치), 멈출 때는 SIGTERM 후 5분(`TimeoutStopSec`) 동안 마지막 판독·발행을 기다린다. 이미 돌고 있는 캡처는 일일 작업이 다시 돌아도 건드리지 않는다.
- 기록기(`start_watchers.sh`)는 각각 `owcskr-<이름>` 유닛으로 뜨고, 죽으면 30초 뒤 다시 시작한다. 모든 `systemd-run` 유닛은 `.env`를 `EnvironmentFile=`로 받는다 (안 그러면 `GH_TOKEN` 등이 없다).
- 경기일마다: 첫 경기 5분 전 `matchday_check.py`, 2분 뒤 `soop_quality.py`, 캡처 시작부터 30분마다 `healthcheck.py`. OBS나 기록기가 없는 서버에서는 그 점검을 건너뛰고 로그에만 남긴다. 지난 날짜의 타이머는 다음 날 일일 작업이 정리한다.

## 감시 (healthchecks, 최신성)
- [healthchecks.io](https://healthchecks.io)(무료)에 체크 두 개를 만들고 ping URL을 `.env`에 넣는다.
  - `OWCSKR_HC_DAILY`: 주기 1일, 유예 2시간. 일일 작업이 성공하면 ping, 실패하면 `/fail`. 서버가 꺼지거나 회수되거나 타이머가 아예 안 돌면 healthchecks가 알린다.
  - `OWCSKR_HC_LIVE`: 캡처 시작 때 `/start`, 정상 종료 때 ping, 실패 때 `/fail`. 경기일에만 오므로 주기는 길게(예: 7일) 잡고, 시작 후 오래 끝나지 않는 것을 보는 용도로 쓴다.
  - ping은 `curl -fsS -m 10 --retry 3`. ping이 실패해도 작업은 실패하지 않는다.
- `tools/healthcheck.py`: 배포된 사이트(`https://owticker.com/owcs-ver.json`)의 빌드 시각을 읽어 경기 중에는 30분, 평소에는 6시간보다 오래됐으면 알린다 (한 번 알리고 3시간 뒤 다시, 회복되면 한 번). 지금 읽는 값은 `checked`(마지막 사이트 빌드 시각)다. 데이터 빌드가 실패해도 이전 데이터를 다시 배포하면서 이 값은 새로 찍히므로, "빌드가 아예 안 돈다"는 잡지만 "빌드는 도는데 데이터가 멈췄다"는 못 잡는다. 사이트에 `dataBuilt` 필드가 생기면(사이트 쪽 수정 P1-04) 자동으로 그 값을 쓴다.

## 서버로 따로 옮겨야 하는 것 (저장소에 없음)
저작권이나 비공개 문제로 git에 없는 파일들이다. 기존 PC에서 `scp`/`rsync`로 같은 경로에 복사한다.
- `data/vod/` 중 학습/기준 이미지: `maps/m_3480.png`, `maps/m_9465.png`, `hi_3466.png`, `maps/m_*.png`, `p1a/frames/m0*_totals_*.png` (`live_capture.py`, `ocr_run.py`가 시작할 때 읽음)
- `data/name_lib/`, `data/header_lib/`, `data/digit_lib/`, `data/ref/`
- 사이트 기록기 폴더 (`score_watch.py` 등) → `.env`의 `OWCSKR_SITE_DIR`. 경로에 공백이 있으면 따옴표로 감싼다. 기록기의 윈도우 전용 코드(`C:\`, `tasklist`, `powershell`, `pythonw`, `APPDATA`)와 의존 패키지는 따로 점검해야 한다.

## 확인
```bash
.venv/bin/python -I tools/schedule_today.py --upcoming --dry    # 앞으로 14일 경기일과 캡처 시간
systemctl --user list-timers 'owcskr-*'                          # 등록된 타이머
systemctl --user status 'owcskr-live-*'                          # 돌고 있는 캡처
journalctl --user -u 'owcskr-*' -n 50                            # 유닛 로그 (점검 스크립트의 stderr 포함)
tail -f data/live/daily.log data/live/task.log
.venv/bin/python -I tools/healthcheck.py --quiet                 # 사이트 최신성
.venv/bin/python -m pytest tests
```
해제: `bash tools/unregister_tasks.sh`

윈도우 PC와 서버를 같이 돌리면 같은 경기를 두 곳에서 캡처하고 발행한다. 서버를 정식으로 등록하는 날 PC에서 `OWCSKR_예약해제.bat`을 실행한다.

## 아직 남은 일
- OBS 없이 프레임 받기 (SOOP HLS → ffmpeg). 지금 `run_live.sh`는 OBS를 가상 화면(xvfb)에서 띄운다.
- 사이트 기록기(`score_watch.py` 등)도 OBS에서 화면을 받으므로 같이 바꿔야 한다.
- 사이트 `owcs-ver.json`에 데이터 빌드 성공 시각(`dataBuilt`) 추가 (사이트 저장소, P1-04).
