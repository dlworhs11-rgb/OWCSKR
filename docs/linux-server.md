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

## 프레임 원천: 서버는 HLS를 권장
`.env`의 `OWCSKR_FRAME_SOURCE`가 캡처(`live_capture.py`)의 화면 입구를 고른다.
- `hls` (**서버 권장**, `.env.example` 값): SOOP 방송 HLS를 `yt-dlp` + `ffmpeg`로 직접 받는다(`tools/frames.py`, `docs/hls-capture.md`). OBS도 가상 화면도 없다: `run_live.sh`는 `Xvfb`를 띄우지 않고, `matchday_check.py`·`soop_quality.py`는 OBS 점검을 건너뛰고 로그에만 남긴다.
  - `ffmpeg`는 apt(아래 설치 명령에 포함), `yt-dlp`는 venv에 `requirements.txt`로 설치된다(버전 고정, 일부러 올린다). `tools/env.sh`가 `.venv/bin`을 PATH 앞에 넣으므로 systemd 유닛에서도 찾는다. 다른 경로면 `FFMPEG_CMD`, `YTDLP_CMD`.
  - `OWCSKR_HLS_CHANNEL`: SOOP 채널 id (기본 `owesports`). `OWCSKR_HLS_KEYFRAMES=1`: 키프레임만 디코딩(CPU가 크게 줄고 프레임 시각이 키프레임 간격에 맞춰짐). 경기일에 `tools/frames_probe.py --keyframes-only`로 간격을 본 뒤 켠다. 기본 `0`.
- `obs` (기본값, 값이 없을 때): OBS 브라우저 소스. 윈도우 PC는 이 경로 그대로다. 리눅스에서는 `run_live.sh`가 `Xvfb`를 띄운다(아래 "시작 전에" 참고).
- 이 세 값은 `live_capture.py`가 직접 읽는다. 사이트 기록기(`score_watch.py` 등)는 아직 OBS 화면을 읽는다(아래 "아직 남은 일").

## 시작 전에 확인할 것
- **OBS 방식 캡처는 ARM에서 확인되지 않았다** (`OWCSKR_FRAME_SOURCE=obs`일 때만 해당). Ubuntu의 apt `obs-studio`에는 브라우저 소스(CEF)가 빠져 있을 가능성이 크고, 공식 OBS PPA는 amd64만 있다. ARM VM에서 아래를 먼저 해 본다.
  ```bash
  xvfb-run -a .venv/bin/python -I tools/obs_setup.py start 'https://vod.sooplive.com/player/209539901?change_second=3440'
  .venv/bin/python -I tools/obs_snap.py 6 10      # data/live/snap_report.txt에 실제 화면이 찍혔는지
  ```
  검은 화면이거나 `CreateInput`이 실패하면 OBS 경로는 포기하고 `OWCSKR_FRAME_SOURCE=hls`로 돌린다(위). 사이트 기록기(`score_watch.py` 등)도 OBS 화면을 읽으므로 같이 바꿔야 한다.
- **HLS 첫 확인**: 다음 경기일에 `.venv/bin/yt-dlp -F https://play.sooplive.com/owesports`(비로그인 화질)와 `.venv/bin/python -I tools/frames_probe.py --count 3`을 돌려 본다. 첫 1~2 경기일은 PC 결과와 비교한다(`docs/hls-capture.md`).
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
- `run_daily.sh` 순서: (캡처가 안 돌면) `git pull --ff-only` → `run-lp.mjs --discover --strict` (`competitions.json`/`active.json`이 바뀌면 `OWCSKR_AUTOCOMMIT=1`일 때 커밋, `OWCSKR_AUTOPUSH=1`일 때 push) → `run-lp.mjs --active-only --strict` → `build.mjs` → `republish_recent.py` → `schedule_today.py --upcoming` → 백업 → 다시보기 댓글 → 사이트 최신성 점검. 단계가 실패해도 다음 단계를 돌리고, 끝에서 실패 목록과 출력 끝부분을 한 번에 알린다. 실패가 있으면 종료 코드 1 (`run-lp` 종료 코드 2 = 일부 페이지 실패, git pull/push 실패, 최신성 점검은 경고: 알리기만 한다).
- 코드 받기(`git pull`): 일일 작업이 매번 다시 쓰는 추적 파일(`data/lp/`, `competitions.json`, `active.json`)은 "로컬 변경"으로 치지 않는다. 들어오는 커밋이 그 파일을 건드려 pull이 거부되면 그 파일만 HEAD로 되돌리고(바로 뒤 단계가 다시 받는다) 한 번 더 pull 한다. 그 밖의 파일을 서버에서 고쳤으면 pull을 건너뛰고 경고로 알린다(`git stash`나 `git checkout`으로 정리). push가 거부되면(원격이 그사이 바뀜) 발견 커밋을 되돌리고 변경은 작업 트리에 남긴다: 다음 날 pull 뒤에 다시 커밋한다.
- 서버 권장값은 `OWCSKR_AUTOCOMMIT=1`과 `OWCSKR_AUTOPUSH=1`을 **함께** 켜는 것이다(사이트가 서버가 찾은 스테이지 목록을 쓰게 하려면). `AUTOCOMMIT=1`만 켜면 로컬 커밋이 쌓여 원격이 바뀐 날부터 `git pull --ff-only`가 계속 실패한다.
- `owcskr-live-<날짜>`: `run_live.sh HOURS DATE`. 처음 시작할 때 끝나는 시각(지금 + HOURS)을 `data/live/<날짜>/until.txt`에 적고 `live_capture.py --until`로 넘긴다. 죽으면 60초 뒤 다시 시작하고(`Restart=on-failure`), 다시 시작해도 같은 시각에 끝난다. `live_capture.py` 시작 점검 실패(종료 코드 2)와 "캡처는 끝났는데 마지막 판독·발행 실패"(종료 코드 4)는 다시 시작하지 않는다(`RestartPreventExitStatus=2 4`). 하루 요약이 나간 날(`data/live/<날짜>/summary.txt`)은 다시 시작해도 바로 끝난다. 끝 시각이 지난 뒤의 재시작은 프레임은 있는데 요약이 없을 때(끝 무렵 충돌)만 마지막 판독·발행·요약을 한 번 돌린다. `OWCSKR_FRAME_SOURCE=obs`이고 화면이 없는 서버에서는 `Xvfb`를 직접 띄운다(`xvfb-run`은 멈출 때 먼저 죽어서 쓰지 않는다). `hls`면 띄우지 않는다. 같은 날 두 번 뜨지 않게 `flock`으로 잠근다. 자정을 넘긴 캡처는 그사이 재부팅해도 부팅 일일 작업이 어제 날짜까지 보고 다시 띄운다. `RuntimeMaxSec`는 일정 길이 + 1시간(안전장치), 멈출 때는 SIGTERM 후 5분(`TimeoutStopSec`) 동안 마지막 판독·발행을 기다린다. 이미 돌고 있는 캡처는 일일 작업이 다시 돌아도 건드리지 않는다.
- 기록기(`start_watchers.sh`)는 각각 `owcskr-<이름>` 유닛으로 뜨고, 죽으면 30초 뒤 다시 시작한다. 모든 `systemd-run` 유닛은 `.env`를 `EnvironmentFile=`로 받는다 (안 그러면 `GH_TOKEN` 등이 없다).
- 경기일마다: 첫 경기 5분 전 `matchday_check.py`, 2분 뒤 `soop_quality.py`, 캡처 시작부터 15분마다 `healthcheck.py`. OBS나 기록기가 없는 서버(`OWCSKR_FRAME_SOURCE=hls` 포함)에서는 그 점검을 건너뛰고 로그에만 남긴다. 지난 날짜의 타이머는 다음 날 일일 작업이 정리한다.

## 감시 (healthchecks, 최신성)
- [healthchecks.io](https://healthchecks.io)(무료)에 체크 두 개를 만들고 ping URL을 `.env`에 넣는다.
  - `OWCSKR_HC_DAILY`: 주기 1일, 유예 2시간. 일일 작업이 성공하면 ping, 실패하면 `/fail`. 서버가 꺼지거나 회수되거나 타이머가 아예 안 돌면 healthchecks가 알린다.
  - `OWCSKR_HC_LIVE`: 캡처 시작 때 `/start`, 정상 종료 때 ping, 실패 때 `/fail`. healthchecks는 `/start` 뒤 유예 시간 안에 끝 ping이 없으면 알리므로 **유예는 가장 긴 캡처보다 길게(14시간)** 잡는다. 경기일에만 오므로 주기는 길게(예: 7일) 잡고, 스테이지 사이 휴식기(몇 주)에는 체크를 일시 정지한다(안 그러면 휴식기마다 알림).
- 윈도우 PC: 파이썬 도구는 모두 `.env`를 읽지만(`platform_util`이 가져올 때 읽음), `run_*.bat`의 healthchecks ping(`curl`)은 bat이 직접 보내므로 `OWCSKR_HC_*`를 **사용자 환경 변수**로 넣어야 한다.
  - ping은 `curl -fsS -m 10 --retry 3`. ping이 실패해도 작업은 실패하지 않는다.
- `tools/healthcheck.py`: 배포된 사이트(`https://owticker.com/owcs-ver.json`)의 빌드 시각을 읽어 경기 중에는 30분, 평소에는 6시간보다 오래됐으면 알린다 (한 번 알리고 3시간 뒤 다시, 회복되면 한 번). 경기일에는 캡처 시작부터 **15분마다** 돌므로 사이트 빌드가 멈추면 30~45분 안에 알림이 온다. "경기 중"은 `matches.json`의 경기와, 팀이 아직 TBD라 `matches.json`에 없는 플레이오프 경기(`data/lp`, `schedule_today.playoff_matches`)를 함께 본다(경기 시작 15분 전부터 예상 종료 + 30분까지). 사이트를 못 읽으면(네트워크 등) **두 번 연속** 실패했을 때만 알린다. 일일 작업의 `--quiet` 실행은 한 번뿐이라 30초 뒤 한 번 더 읽어 본다. 지금 읽는 값은 `checked`(마지막 사이트 빌드 시각)다. 데이터 빌드가 실패해도 이전 데이터를 다시 배포하면서 이 값은 새로 찍히므로, "빌드가 아예 안 돈다"는 잡지만 "빌드는 도는데 데이터가 멈췄다"는 못 잡는다. 사이트에 `dataBuilt` 필드가 생기면(사이트 쪽 수정 P1-04) 자동으로 그 값을 쓴다.

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
- HLS 원천의 실제 경기일 확인(화질, 키프레임 간격, PC 결과와 비교)과 새 화질에 맞춘 사전 재구축 (`docs/hls-capture.md`).
- 사이트 기록기(`score_watch.py` 등)도 OBS에서 화면을 받으므로 같이 바꿔야 한다.
- 사이트 `owcs-ver.json`에 데이터 빌드 성공 시각(`dataBuilt`) 추가 (사이트 저장소, P1-04).
