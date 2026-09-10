# Project G-One

Project G-One은 WireGuard 기반 사설망, 파일 서비스와 동의 기반 원격 지원을 하나의
Python 웹 관리 환경에서 운영하기 위한 중앙관리형 플랫폼입니다. 중앙 관리자는 SSO와
최소 권한 정책을 바탕으로 사용자·장치·서비스 연결을 통제하고 감사할 수 있습니다.

> 이 문서는 프로젝트의 첫 진입점입니다. 프로젝트의 상세 방향과 의사결정 기준은
> [프로젝트 방향 문서](docs/PROJECT_DIRECTION.md)에서 관리합니다. Windows 프로그램의 상세
> 기준은 [Windows 클라이언트 및 서비스 요구사항](docs/WINDOWS_CLIENT_AND_SERVICE_REQUIREMENTS.md)을 따릅니다.

## 현재 상태

- 단계: **제어면 백엔드 기반 구축**
- 확정된 내용: Windows 전용 클라이언트, 매 실행 대화형 로그인, 자동 VPN·SMB 구성,
  WireGuard 중계, 파일별 권한, 티켓·동의 기반 원격 지원, 자체 호스팅과 멀티테넌시
- 통합 후보: Authentik, Synology, Proxmox, Vaultwarden
- 결정이 필요한 내용: 배포 규모, 지원 Windows 버전, 구체 프레임워크, 원격 지원 프로토콜, 운영 목표

SMB를 1차 대상으로 삼지만 NFS, WebDAV 및 다른 프로토콜의 추가를 막지 않는 어댑터
구조를 지향합니다. 세부 구현은 위협 모델과 대상 환경을 검증한 뒤 확정합니다.

## 프로젝트 목표

1. SSO 기반으로 사용자와 장치를 등록하고 접근을 신속하게 회수합니다.
2. WireGuard 피어 간 연결과 내부 서비스 접근을 기본 거부 정책으로 관리합니다.
3. SMB 중심의 파일 서비스를 제공하면서 프로토콜 확장성을 유지합니다.
4. 접속 장치에서 동의를 받은 뒤 최소 권한 원격 지원 세션을 연결합니다.
5. 외부 서버 통합을 격리된 어댑터로 확장하고 모든 고위험 작업을 감사합니다.

## 백엔드 시작하기

Python 3.12 이상에서 제어면 API를 실행할 수 있습니다. 현재 인증기는 OIDC 연결 전 개발
단계의 HS256 액세스 토큰 검증기이며, 개발 외 환경에서는 반드시 32바이트 이상의 별도
서명을 설정해야 합니다.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
export G_ONE_JWT_SECRET='replace-with-at-least-32-random-bytes'
uvicorn g_one.main:app --reload
```

서버는 시작할 때 Alembic 마이그레이션을 자동 적용합니다. 스키마만 미리 반영하거나 변경
누락 여부를 확인하려면 다음 명령을 사용합니다.

```bash
alembic upgrade head
alembic check
```

API 문서는 `http://127.0.0.1:8000/docs`, 상태 확인은 `/healthz`와 `/readyz`에서 제공됩니다.
관리 콘솔은 `http://127.0.0.1:8000/`에서 바로 확인할 수 있습니다.
콘솔 첫 화면에서는 사용자 ID, 워크스페이스와 `G_ONE_CONSOLE_PASSWORD`를 입력해 단기
관리 세션을 발급받습니다. 설치 스크립트가 이 암호를 `.env`에 자동 생성하며, 운영자는
`python3 scripts/configure_server.py show`로 마스킹된 설정을 확인한 뒤 서버에서 직접
`.env`의 값을 확인할 수 있습니다. 콘솔에서 실제 API를 통해 장치 등록·접근 회수, 원격
지원 요청 및 감사 로그 조회를 수행할 수 있습니다.
기본 SQLite 파일은 `g-one.db`이며 `G_ONE_DATABASE_URL`로 변경할 수 있습니다. 현재 구현은
장치 등록·폐기, tenant 범위 조회, 원격 지원 요청·동의·종료 및 감사 조회의 첫 수직
슬라이스와 WireGuard VPN 서버·피어 관리를 제공합니다. 콘솔의 **VPN 네트워크**에서 서버
CIDR과 공개 엔드포인트를 설정한 뒤 피어를 추가하면 클라이언트 설정이 한 번만 표시됩니다.
생성된 클라이언트 개인 키는 DB에 저장하지 않으므로 즉시 안전하게 보관해야 합니다.
**라우팅 관리** 탭에서는 피어별 `AllowedIPs`를 CIDR 목록으로 제한할 수 있습니다. 기본값은
VPN 내부 대역인 split tunnel이며, `0.0.0.0/0, ::/0` 전체 터널을 선택하기 전에는 서버의
IP forwarding, 방화벽 및 NAT 정책을 별도로 구성해야 합니다. 이미 배포된 피어의 경로를
변경했다면 해당 클라이언트 설정에도 같은 `AllowedIPs`를 반영해야 합니다.
실제 인터넷 연결 배포 전에는 Authentik OIDC/JWKS 검증과 MariaDB
백업·복구 훈련을 완료해야 합니다.

### Docker Compose + MariaDB 배포

운영 환경은 MariaDB 11.4를 사용합니다. 최초 설치 스크립트는 JWT 및 DB 암호를 자동으로
생성하고, Compose 설정 검증, 이미지 준비, 웹 이미지 빌드와 서비스 시작까지 수행합니다.
스크립트를 다시 실행해도 기존 운영자 설정과 비밀은 덮어쓰지 않습니다.

```bash
python3 scripts/setup_server.py
```

위 명령 하나가 `.env` 생성, 이미지 준비, 웹 이미지 빌드, 컨테이너 시작, 준비 상태 및
502 원인 점검까지 순서대로 완료합니다. **저장소를 이미 내려받은 서버에서는 아래 한 줄만
실행하면 됩니다.**

```bash
cd /path/to/Project-G-One && python3 scripts/setup_server.py
```

설치기는 현재 사용자의 Docker 소켓 권한을 먼저 확인합니다. 직접 접근할 수 없으면 Docker
명령에만 `sudo`를 사용하며, 프로젝트가 과거의 `sudo git` 실행 등으로 root 소유가 된
경우에는 데이터를 변경하기 전에 정확한 소유권 복구 명령을 출력하고 중단합니다. 따라서
`.env`를 root 소유로 새로 만들어 이후 실행을 망가뜨리지 않습니다.

명령이 끝난 뒤 리버스 프록시 upstream은 프록시 위치에 맞게 지정합니다.

- 같은 서버의 프록시: `http://127.0.0.1:8000`
- 다른 서버의 프록시: `http://G_ONE_SERVER_IP:8000`

`502 Bad Gateway`가 나타나면 G-One 서버에서 다음 한 줄로 컨테이너, API 준비 상태,
정적 파일과 프록시 대상 주소를 한 번에 검사하십시오.

```bash
cd /path/to/Project-G-One && python3 scripts/manage_server.py doctor
```

배포 중 `address already in use`가 발생하면 권한 문제가 아니라 HTTP 포트 충돌입니다.
`manage_server.py start`는 이제 시작 전에 포트 점유자를 확인하고 이전 G-One 웹 컨테이너나
레거시 G-One Uvicorn 프로세스만 정리합니다. 관련 없는 서비스가 점유 중이면 해당 서비스를
자동 종료하지 않고 안전한 포트 변경 명령을 안내합니다.

설치부터 프록시 연결까지의 정확한 순서는 [리버스 프록시 배포 가이드](docs/REVERSE_PROXY.md)의
**처음 설치: 순서대로 실행** 절을 따르십시오.

기본 공개 포트는 외부 리버스 프록시가 접속할 수 있도록 호스트의 `0.0.0.0:8000`에
바인딩됩니다. 반드시 방화벽에서 이 포트를 리버스 프록시 서버 IP에만 허용하고 외부에는
HTTPS 프록시 포트만 공개해야 합니다. 같은 호스트에서 프록시를 실행한다면
`python3 scripts/configure_server.py set http-bind 127.0.0.1`로 축소할 수 있습니다.
전체 프록시 설정과 점검 방법은 [리버스 프록시 배포 가이드](docs/REVERSE_PROXY.md)를
참고하십시오. 포트 변경은 `.env`의 `G_ONE_HTTP_PORT`를 수정합니다.
초기 구성만 만들고 나중에 시작하려면 `--no-start`를 사용합니다.

```bash
python3 scripts/setup_server.py --no-start
```

### 서버 설정 및 관리

설정 스크립트는 허용된 항목만 안전하게 변경하며 `show` 출력에서는 암호를 숨깁니다.
설정 변경 후에는 서버를 재시작해야 합니다.

```bash
python3 scripts/configure_server.py show
python3 scripts/configure_server.py set http-port 8080
python3 scripts/configure_server.py set db-name g_one
```

일상 운영은 관리 스크립트 하나로 처리할 수 있습니다.

```bash
python3 scripts/manage_server.py start       # 빌드, 기동, 준비 상태 확인
python3 scripts/manage_server.py status      # 컨테이너 상태
python3 scripts/manage_server.py logs        # 최근 로그 200줄
python3 scripts/manage_server.py logs --follow
python3 scripts/manage_server.py restart
python3 scripts/manage_server.py update      # 이미지 갱신 후 재기동
python3 scripts/manage_server.py stop
```

MariaDB 데이터는 `g-one-database` Docker 볼륨에 보존되며 `stop`은 볼륨을 삭제하지
않습니다. 데이터까지 제거하는 `docker compose down --volumes`는 초기화가 명확히 필요한
경우에만 직접 실행해야 합니다.

### WireGuard 운영 설정

설치 스크립트는 서버 개인 키를 `.env`에 생성하고 Compose는 UDP 51820 포트와 `NET_ADMIN`
권한을 웹 컨테이너에 제공합니다. 호스트 방화벽에서 `${G_ONE_WIREGUARD_PORT:-51820}/udp`를
허용하고 콘솔에 입력한 엔드포인트 DNS가 서버 공인 IP를 가리키게 하십시오. 포트를 바꾸면
`.env`와 웹 서버 설정의 포트를 동일하게 변경한 후 컨테이너를 다시 시작해야 합니다.
런타임 적용이 필요 없는 개발 환경에서는 `G_ONE_WIREGUARD_APPLY=false`를 사용합니다.

생성되는 클라이언트 설정은 VPN CIDR만 라우팅하는 split tunnel 방식입니다. IPv4 서버
설정에는 전달 및 masquerade 규칙이 자동으로 적용되므로 클라이언트 `AllowedIPs`에 LAN
CIDR을 추가하면 Docker 호스트가 도달할 수 있는 LAN에 접속할 수 있습니다. 단, 목적지
호스트나 상위 방화벽에서도 해당 트래픽을 허용해야 합니다. IPv6 라우팅에는 배포 환경에
맞는 별도 방화벽 정책이 필요합니다. 웹 프로세스에 네트워크 관리 권한이 부여되므로
콘솔은 반드시 HTTPS 리버스 프록시 뒤에 두고 API 포트를 신뢰된 프록시로만 제한하십시오.

## 문서 구조

```text
.
├── README.md                  # 프로젝트 소개와 빠른 시작
├── docs/
│   ├── PROJECT_DIRECTION.md                    # 제품 요구사항, 아키텍처, 보안, MVP와 의사결정 기록
│   ├── THREAT_MODEL.md                         # 신뢰 경계, STRIDE 위험과 출시 차단 조건
│   └── WINDOWS_CLIENT_AND_SERVICE_REQUIREMENTS.md # Windows 앱·서비스 상세 요구사항
├── src/g_one/alembic/         # 배포 간 데이터 보존을 위한 Alembic 스키마 이력
├── src/g_one/                 # FastAPI 제어면 서버
├── tests/                     # tenant 격리와 동의 흐름 API 테스트
├── pyproject.toml             # Python 패키지 및 개발 의존성
└── LICENSE                    # GNU GPL v3 라이선스 전문
```

## 작업 원칙

- 하나의 변경은 하나의 명확한 목적을 갖습니다.
- 기능 작업은 사용자 가치와 검증 방법을 함께 기록합니다.
- 범위가 커지면 핵심 사용자 여정을 기준으로 우선순위를 다시 정합니다.
- 중요한 결정은 방향 문서의 **의사결정 기록**에 남깁니다.
- 코드가 추가되면 자동화된 테스트와 실행 방법을 함께 제공합니다.

## 기여 방법

1. 작업 전에 관련 이슈 또는 문서에서 목적과 범위를 합의합니다.
2. 작은 단위의 브랜치에서 변경합니다.
3. 변경 이유와 검증 결과를 포함해 리뷰를 요청합니다.
4. 방향이 달라지는 변경은 코드보다 문서를 먼저 갱신합니다.

구체적인 브랜치·커밋·리뷰 규칙은 개발 환경이 정해질 때 보완합니다.

## 라이선스

이 프로젝트는 [GNU General Public License v3.0](LICENSE)에 따라 배포됩니다.
