# 리눅스 서버에서 돌리기 (Oracle Cloud 등)

윈도우 PC와 같은 코드가 리눅스에서도 돈다. 차이는 `tools/platform_util.py` 한 곳에 모았다.

| 윈도우 | 리눅스 |
|---|---|
| 작업 스케줄러 `OWCSKR\Daily` | systemd 사용자 타이머 `owcskr-daily` (09:00 KST + 부팅 3분 뒤) |
| `OWCSKR\LiveCapture_<날짜>` | `owcskr-live-<날짜>` (타이머 + 서비스, 죽으면 다시 시작) |
| `OWCSKR\MatchdayCheck_<날짜>`, `SoopQuality_<날짜>`, `Freshness_<날짜>`, `SiteDispatch_<날짜>` | `owcskr-check-<날짜>`, `owcskr-soop-<날짜>`, `owcskr-fresh-<날짜>`, `owcskr-dispatch-<날짜>` |
| `tools/*.bat`, `register_tasks.ps1` | `tools/*.sh` (`register_tasks.sh`, `run_daily.sh`, `run_live.sh`, `start_watchers.sh`) |
| 메시지 창 (`popup`) | 디스코드 웹훅 (`OWCSKR_DISCORD_WEBHOOK`), 없으면 로그만 |
| `%APPDATA%\obs-studio` | `~/.config/obs-studio` |
| `gh auth login` | `.env`의 `GH_TOKEN` (+ `gh auth setup-git`) |

## 프레임 원천: 서버는 HLS를 권장
`.env`의 `OWCSKR_FRAME_SOURCE`가 캡처(`live_capture.py`)의 화면 입구를 고른다.
- `hls` (**서버 권장**, `.env.example` 값): SOOP 방송 HLS를 `yt-dlp` + `ffmpeg`로 직접 받는다(`tools/frames.py`, `docs/hls-capture.md`). OBS도 가상 화면도 없다: `run_live.sh`는 `Xvfb`를 띄우지 않고, `matchday_check.py`·`soop_quality.py`는 OBS 점검을 건너뛰고 로그에만 남긴다.
  - `ffmpeg`는 apt(아래 설치 명령에 포함), `yt-dlp`는 venv에 `requirements.txt`로 설치된다(버전 고정, 일부러 올린다). `tools/env.sh`가 `.venv/bin`을 PATH 앞에 넣으므로 systemd 유닛에서도 찾는다. 다른 경로면 `FFMPEG_CMD`, `YTDLP_CMD`.
  - `OWCSKR_HLS_CHANNEL`: SOOP 채널 id (기본 `owesports`). `OWCSKR_HLS_KEYFRAMES=1`: 키프레임만 디코딩(CPU가 크게 줄고 프레임 시각이 키프레임 간격에 맞춰짐). 경기일에 `tools/frames_probe.py --keyframes-only`로 간격을 본 뒤 켠다. 기본 `0`.
- `obs` (기본값, 값이 없을 때): OBS 브라우저 소스. 대소문자는 가리지 않고, `obs`·`hls`가 아닌 값도 경고 한 줄(`task.log`, stderr)을 남기고 `obs`로 읽는다(`live_capture.py`, `run_live.sh`, `selfcheck.py`, 경기일 점검이 모두 같다). 윈도우 PC는 이 경로 그대로다. 리눅스에서는 `run_live.sh`가 `Xvfb`를 띄운다(아래 "시작 전에" 참고).
- `OWCSKR_HLS_*`는 `live_capture.py`만 읽는다. 사이트 기록기(`score_watch.py` 등)는 아직 OBS 화면을 읽는다(아래 "아직 남은 일").

## 시작 전에 확인할 것
- **OBS 방식 캡처는 ARM에서 확인되지 않았다** (`OWCSKR_FRAME_SOURCE=obs`일 때만 해당). Ubuntu의 apt `obs-studio`에는 브라우저 소스(CEF)가 빠져 있을 가능성이 크고, 공식 OBS PPA는 amd64만 있다. ARM VM에서 아래를 먼저 해 본다.
  ```bash
  xvfb-run -a .venv/bin/python -I tools/obs_setup.py start 'https://vod.sooplive.com/player/209539901?change_second=3440'
  .venv/bin/python -I tools/obs_snap.py 6 10      # data/live/snap_report.txt에 실제 화면이 찍혔는지
  ```
  검은 화면이거나 `CreateInput`이 실패하면 OBS 경로는 포기하고 `OWCSKR_FRAME_SOURCE=hls`로 돌린다(위). 사이트 기록기(`score_watch.py` 등)도 OBS 화면을 읽으므로 같이 바꿔야 한다.
- **HLS 첫 확인**: 다음 경기일에 `.venv/bin/yt-dlp -F https://play.sooplive.com/owesports`(비로그인 화질)와 `.venv/bin/python -I tools/frames_probe.py --count 3`을 돌려 본다. 첫 1~2 경기일은 발행을 끄고(`OWCSKR_PUBLISH=0`) PC 결과와 비교한다(아래 "섀도 운영", `docs/hls-capture.md`).
- **Oracle Always Free는 유휴 인스턴스를 회수한다** (7일 동안 CPU·네트워크·메모리 사용이 낮으면). 경기 없는 주에는 일일 작업 몇 분뿐이라 회수 대상이 된다. 계정을 **PAYG(종량제)로 올린다**: Always Free 한도 안에서는 요금이 없고 회수 대상에서 빠진다. 부하를 일부러 만드는 방법은 쓰지 않는다. 회수돼도 알 수 있게 아래 healthchecks를 꼭 설정한다.

## 처음 설치 (Ubuntu 22.04/24.04, ARM 또는 x86)
전용 계정(예: `owcskr`, sudo 없음)으로 돌리는 것을 권한다. 설치 명령 중 `sudo`는 관리자 계정에서 한다.
```bash
sudo timedatectl set-timezone Asia/Seoul          # 날짜 계산(date.today)이 한국 날짜와 맞도록
sudo apt update
sudo apt install -y git python3-venv tesseract-ocr ffmpeg gh curl dbus-user-session
# Node: 배포판 nodejs는 22.04에서 12.x라 못 쓴다 (collector는 20 이상, package.json engines). NodeSource 22.x (20은 2026-04-30에 지원 종료, 사이트 Actions도 22):
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node --version                                     # v22.x 인지 확인
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
- `run_daily.sh` 순서: (캡처가 안 돌면) `git pull --ff-only` → `run-lp.mjs --discover --strict` (`competitions.json`/`active.json`이 바뀌면 `OWCSKR_AUTOCOMMIT=1`일 때 커밋, `OWCSKR_AUTOPUSH=1`일 때 push) → `run-lp.mjs --active-only --strict` → `build.mjs` → `republish_recent.py` → 알림 유닛(`owcskr-alert@.service`) 확인 → `schedule_today.py --upcoming` → 백업 → 다시보기 댓글 → 사이트 최신성 점검. 단계가 실패해도 다음 단계를 돌리고, 끝에서 실패 목록과 출력 끝부분을 한 번에 알린다. 실패가 있으면 종료 코드 1 (`run-lp` 종료 코드 2 = 일부 페이지 실패, git pull/commit/push 실패, 알림 유닛 쓰기 실패, 최신성 점검은 경고: 알리기만 한다).
- 코드 받기(`git pull`): 일일 작업이 매번 다시 쓰는 추적 파일(`data/lp/`, `competitions.json`, `active.json`)은 "로컬 변경"으로 치지 않는다. 들어오는 커밋이 그 파일을 건드려 pull이 거부되면 그 파일만 HEAD로 되돌리고(바로 뒤 단계가 다시 받는다) 한 번 더 pull 한다. 그 밖의 파일을 서버에서 고쳤으면 pull을 건너뛰고 경고로 알린다(`git stash`나 `git checkout`으로 정리). push가 거부되면(원격이 그사이 바뀜) 발견 커밋을 되돌리고 변경은 작업 트리에 남긴다: 다음 날 pull 뒤에 다시 커밋한다.
- 서버 권장값은 `OWCSKR_AUTOCOMMIT=1`과 `OWCSKR_AUTOPUSH=1`을 **함께** 켜는 것이다(사이트가 서버가 찾은 스테이지 목록을 쓰게 하려면). `AUTOCOMMIT=1`만 켜면 로컬 커밋이 쌓여 원격이 바뀐 날부터 `git pull --ff-only`가 계속 실패한다.
- `owcskr-live-<날짜>`: `run_live.sh HOURS DATE`. 처음 시작할 때 끝나는 시각(지금 + HOURS)을 `data/live/<날짜>/until.txt`에 적고 `live_capture.py --until`로 넘긴다. 죽으면 60초 뒤 다시 시작하고(`Restart=on-failure`), 다시 시작해도 같은 시각에 끝난다. `live_capture.py` 시작 점검 실패(종료 코드 2)와 "캡처는 끝났는데 마지막 판독·발행 실패"(종료 코드 4), `.env` 형식 오류(78)는 다시 시작하지 않는다(`RestartPreventExitStatus=2 4 78`). 1·2·4는 `run_live.sh`가 직접 알리고(인자가 잘못돼 캡처를 시작하지 못한 종료 코드 2 포함) 유닛의 `OnFailure=` 알림(`notify.py --unit-failed`)은 그 코드를 건너뛴다. 하루 요약이 나간 날(`data/live/<날짜>/summary.txt`)은 다시 시작해도 바로 끝난다. 끝 시각이 지난 뒤의 재시작은 프레임은 있는데 요약이 없을 때(끝 무렵 충돌)만 마지막 판독·발행·요약을 한 번 돌린다. `OWCSKR_FRAME_SOURCE=obs`이고 화면이 없는 서버에서는 `Xvfb`를 직접 띄운다(`xvfb-run`은 멈출 때 먼저 죽어서 쓰지 않는다). `hls`면 띄우지 않는다. 같은 날 두 번 뜨지 않게 `flock`으로 잠근다. 자정을 넘긴 캡처는 그사이 재부팅해도 부팅 일일 작업이 어제 날짜까지 보고 다시 띄운다. `RuntimeMaxSec`는 일정 길이 + 1시간(안전장치), 멈출 때는 SIGTERM 후 5분(`TimeoutStopSec`) 동안 마지막 판독·발행을 기다린다. 이미 돌고 있는 캡처는 일일 작업이 다시 돌아도 건드리지 않는다.
- 기록기(`start_watchers.sh`)는 각각 `owcskr-<이름>` 유닛으로 뜨고, 죽으면 30초 뒤 다시 시작한다. 단 **10분 안에 5번** 시작하면(`StartLimitIntervalSec=10min`, `StartLimitBurst=5`) 포기하고 유닛이 실패 상태가 되며 알림이 간다(아래). 모든 `systemd-run` 유닛은 `.env`를 `EnvironmentFile=`로 받는다 (안 그러면 `GH_TOKEN` 등이 없다).
- **유닛 실패 알림**: `register_tasks.sh`가 `~/.config/systemd/user/owcskr-alert@.service`를 설치한다(일일 작업도 빠졌거나 바뀌었으면 다시 쓴다). 캡처(`owcskr-live-<날짜>`), 기록기, 일일 작업(`owcskr-daily.service`)은 `OnFailure=owcskr-alert@<유닛 이름>.service`를 달고 있어서, 유닛이 완전히 실패하면(재시작 한도 초과, 재시작 안 하는 종료 코드, 강제 종료, 시간 초과) `tools/notify.py --unit-failed <유닛>`이 결과, `journalctl --user -u <유닛>` 마지막 30줄, 그 유닛의 로그 파일(`task.log`, `daily.log`, `<기록기>.log`) 끝을 알린다. 스크립트가 이미 스스로 알린 종료 코드(일일 작업 1, 캡처 1·2·4)는 건너뛰고, 같은 유닛은 30분에 한 번만 알린다. `.env` 형식 오류는 종료 코드 78(`EX_CONFIG`)이라 캡처가 재시작을 반복하지 않고 이 알림으로 온다. **이번 갱신 뒤에는 `bash tools/register_tasks.sh`를 한 번 다시 실행한다**(일일 작업 유닛 파일에 `OnFailure=`를 넣기 위해).
  - `systemd-run -p`로 `[Unit]` 설정(`OnFailure=`, `StartLimitBurst=`, `StartLimitIntervalSec=`)을 넘긴다. systemd 236부터 transient 유닛이 이 설정을 받는다(Ubuntu 22.04는 249, 24.04는 255). 유닛 파일과 달리 `-p` 값은 지정자(`%n`)를 풀지 않으므로 유닛 이름을 그대로 적는다(`owcskr-alert@owcskr-live-2026-10-25.service.service`: 인스턴스가 유닛의 전체 이름). 서버에서 확인: `systemctl --user show -p OnFailure,StartLimitBurst owcskr-live-<날짜>.service`, 알림 시험은 `systemctl --user start owcskr-alert@owcskr-test.service.service`(없는 유닛이라 "result success, exit status 0" 알림이 한 번 온다).
  - 캡처 유닛은 재시작 한도를 따로 두지 않는다(60초 간격이라 기본 한도 10초에 5번에 걸리지 않음). 충돌은 `run_live.sh`가 30분에 한 번 알리고, 끝 시각(`until.txt`)이 반복을 끝낸다.
- 경기일마다: 첫 경기 5분 전 `matchday_check.py`, 첫 경기 2분 뒤 `soop_quality.py`, 캡처 시작부터 15분마다 `healthcheck.py`. OBS가 없거나 `OWCSKR_FRAME_SOURCE=hls`인 서버에서는 OBS 점검을, `OWCSKR_SITE_DIR`가 비어 있으면 기록기 점검을 건너뛰고 로그에만 남긴다. 점검 유닛은 10분(`RuntimeMaxSec`)을 넘기면 멈추고 `OnFailure=` 알림은 없다(스크립트가 스스로 알린다). 지난 날짜의 타이머는 다음 날 일일 작업이 멈추고, 지난 날짜의 유닛(점검, 캡처, 다시보기 댓글, 알림 유닛)은 `reset-failed`로 실패 기록을 지운다: `systemctl --user --failed`에는 아직 손볼 것만 남는다. 돌고 있는 서비스(자정을 넘긴 어제 캡처)는 멈추지 않는다.
- **사이트 빌드 호출 (선택, `OWCSKR_SITE_DISPATCH=1`)**: 캡처 시작부터 끝까지 10분마다 `tools/dispatch_site.py`가 `gh workflow run pages.yml -R dlworhs11-rgb/owcs-kr`를 부른다(`owcskr-dispatch-<날짜>`, 윈도우는 `OWCSKR\SiteDispatch_<날짜>` 작업). cron-job.org 외의 두 번째 트리거다(P1-15). 끝 시각 뒤에는 타이머가 다음 날 아침 정리까지 돌아도 아무것도 하지 않고, 값을 0으로 바꾸면 다음 실행부터 바로 멈춘다. **`GH_TOKEN`에 사이트 저장소(owcs-kr)의 Actions 읽기·쓰기 권한이 필요하다**(fine-grained 토큰: Repository access에 owcs-kr 추가, Permissions → Actions: Read and write. 만료일을 적어 두고 갱신). 3번 연속 실패하면 알리고(3시간 뒤 다시), 다시 되면 한 번 알린다. 로그: `journalctl --user -u 'owcskr-dispatch-*'`, 윈도우 `data\live\dispatch.log`.

## 감시 (healthchecks, 최신성)
- [healthchecks.io](https://healthchecks.io)(무료)에 체크 두 개를 만들고 ping URL을 `.env`에 넣는다.
  - `OWCSKR_HC_DAILY`: 주기 1일, 유예 2시간. 일일 작업이 성공하면 ping, 실패하면 `/fail`. 서버가 꺼지거나 회수되거나 타이머가 아예 안 돌면 healthchecks가 알린다.
  - `OWCSKR_HC_LIVE`: 캡처 시작 때 `/start`, 정상 종료 때 ping, 실패 때 `/fail`. healthchecks는 `/start` 뒤 유예 시간 안에 끝 ping이 없으면 알리므로 **유예는 가장 긴 캡처보다 길게(14시간)** 잡는다. 경기일에만 오므로 주기는 길게(예: 7일) 잡고, 스테이지 사이 휴식기(몇 주)에는 체크를 일시 정지한다(안 그러면 휴식기마다 알림).
- 윈도우 PC: `platform_util`을 가져오는 파이썬 도구(캡처, 점검, 알림, 발행)와 그 하위 프로세스는 `.env`를 읽지만, `run_*.bat`의 healthchecks ping(`curl`)은 bat이 직접 보내므로 `OWCSKR_HC_*`를 **사용자 환경 변수**로 넣어야 한다.
  - ping은 `curl -fsS -m 10 --retry 3`. ping이 실패해도 작업은 실패하지 않는다.
- `tools/healthcheck.py`: 배포된 사이트(`https://owticker.com/owcs-ver.json`)의 빌드 시각을 읽어 경기 중에는 30분, 평소에는 6시간보다 오래됐으면 알린다 (한 번 알리고 3시간 뒤 다시, 회복되면 한 번). 경기일에는 캡처 시작부터 **15분마다** 돌므로 사이트 빌드가 멈추면 30~45분 안에 알림이 온다. "경기 중"은 `matches.json`의 경기와, 팀이 아직 TBD라 `matches.json`에 없는 플레이오프 경기(`data/lp`, `schedule_today.playoff_matches`)를 함께 본다(경기 시작 15분 전부터 예상 종료 + 30분까지). 사이트를 못 읽으면(네트워크 등) **두 번 연속** 실패했을 때만 알린다. 일일 작업의 `--quiet` 실행은 한 번뿐이라 30초 뒤 한 번 더 읽어 본다. 읽는 값은 `owcs-ver.json`의 `dataBuilt`(마지막으로 **데이터 빌드가 성공한** 시각, 사이트 쪽 수정 P1-04)이고, 그 파일에 실패한 데이터 빌드 수 `buildFails`가 있으면 알림에 함께 적는다(지금 사이트 브랜치는 `buildFails`를 `owcs-data.js`에만 쓰므로 이 줄은 아직 나오지 않는다). `dataBuilt`는 데이터 빌드가 실패하면 움직이지 않으므로 사이트 브랜치(owcs-kr `fix/collector-p1`)가 배포되면 "빌드가 아예 안 돈다"와 **"빌드는 도는데 데이터가 멈췄다"**를 둘 다 잡는다. 그 전의 배포본에는 `checked`(마지막 사이트 빌드 시각, 실패한 빌드에도 새로 찍힘)만 있어서 그 값을 쓰고, 그때는 "빌드가 아예 안 돈다"만 잡는다. 알림은 사이트 저장소 README의 "빌드는 누가 일으키나"(빌드 트리거와 토큰)를 가리킨다.

## 서버로 따로 옮겨야 하는 것 (저장소에 없음)
저작권이나 비공개 문제로 git에 없는 파일들이다. 기존 PC에서 `scp`/`rsync`로 같은 경로에 복사한다.
- GAME DATA 기준 이미지 `data/vod/maps/m_3480.png`, `data/vod/maps/m_9465.png` (`live_capture.py`)
- 글자 모델 `data/models/table.npz`, `data/models/totals.npz` (`ocr_run.py`). PC에서 `python -I tools/glyph_models.py --rebuild`로 만든다(`data/models/README.md`). 학습 프레임(`data/vod/`의 나머지)은 서버에 없어도 된다
- `data/name_lib/`, `data/header_lib/`, `data/digit_lib/`, `data/ref/`
- 빠진 것이 있으면 `tools/selfcheck.py`가 fatal로 알리고 캡처가 시작하지 않는다(종료 코드 2)
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
해제: `bash tools/unregister_tasks.sh`. 모든 OWCSKR 타이머를 멈추고 `register_tasks.sh`가 쓴 유닛 파일을 지우며 실패 기록을 지운다. **지금 돌고 있는 캡처와 기록기는 그대로 둔다**(방송 중에 멈추면 그날 나머지를 잃는다): 남긴 유닛과 멈추는 명령을 출력한다. 함께 멈추려면 `bash tools/unregister_tasks.sh --stop-running`. 윈도우의 `OWCSKR_예약해제.bat`도 작업만 지우고 돌고 있는 캡처는 두는 것은 같다.

윈도우 PC와 서버를 같이 돌리면 같은 경기를 두 곳에서 캡처한다. 발행은 한 곳만 해야 하므로, PC가 발행하는 동안 서버는 아래 섀도 운영으로 돌린다. 서버를 정식으로 쓰는 날 PC에서 `OWCSKR_예약해제.bat`을 실행한다.

## 섀도 운영 (발행 끄고 PC와 비교)
첫 1~2 경기일은 PC가 그대로 발행하고 서버는 판독만 한다. 서버 `.env`에 `OWCSKR_PUBLISH=0`(기본 1)을 넣으면:
- `live_capture.py`: 맵마다 판독(`ocr_run.py`)과 조립(`assemble_day.py`)은 하고 `publish_day.py`는 건너뛴다. `task.log`에 `publish off (OWCSKR_PUBLISH=0)`가 남고, 결과는 서버의 `data/live/<날짜>/ocr.json`·`mapstats.json`에만 있다. `gh`나 GitHub 토큰이 없어도 시작 점검은 경고만 한다. 하루 요약 알림에는 `N publishable, publish off (OWCSKR_PUBLISH=0)`로 나온다. 손으로 한 번만 끄려면 `live_capture.py --no-publish`.
- 일일 작업의 `republish_recent.py`: 최근 이틀을 다시 조립만 한다.
- SOOP 다시보기 댓글(`run_live.sh`의 경기 뒤 댓글, 일일 작업의 `replay_comment.py --post`): 올리지 않고 로그에 `publish off`만 남긴다.
- 알림(Discord), healthchecks ping, `OWCSKR_SITE_DISPATCH`(사이트 빌드 호출)는 이 설정과 상관없이 그대로 돈다.

순서:
1. 서버 `.env`에 `OWCSKR_PUBLISH=0`과 `OWCSKR_FRAME_SOURCE=hls`를 넣고 `bash tools/register_tasks.sh`. 바꾼 값은 다음에 시작하는 캡처부터 적용된다(돌고 있는 캡처는 시작할 때 값 그대로).
2. 경기일이 끝나면 서버와 PC의 `data/live/<날짜>/ocr.json`·`mapstats.json`(맵 수, `totalsVerified`, `labelVerified`, 이름)과 두 하루 요약 알림을 비교한다. 새 화질에 맞춰 사전을 다시 만들 프레임은 서버의 `data/live/<날짜>/frames/`에 있다.
3. 맞으면 PC에서 `OWCSKR_예약해제.bat`을 실행하고, 서버 `.env`에서 `OWCSKR_PUBLISH=1`로 바꾼다(줄을 지워도 1).

## 아직 남은 일
- HLS 원천의 실제 경기일 확인(화질, 키프레임 간격, PC 결과와 비교)과 새 화질에 맞춘 사전 재구축 (`docs/hls-capture.md`).
- 사이트 기록기(`score_watch.py` 등)도 OBS에서 화면을 받으므로 같이 바꿔야 한다.
- 사이트 브랜치(owcs-kr `fix/collector-p1`, `owcs-ver.json`에 `dataBuilt`를 내보냄, P1-04) 배포. 그 전에는 최신성 점검이 `checked`로 동작한다. `buildFails`도 `owcs-ver.json`에 넣어야 최신성 알림에 실패 횟수가 나온다.
