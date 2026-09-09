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

API 문서는 `http://127.0.0.1:8000/docs`, 상태 확인은 `/healthz`와 `/readyz`에서 제공됩니다.
관리 콘솔은 `http://127.0.0.1:8000/`에서 바로 확인할 수 있습니다.
개발 환경에서는 콘솔 첫 화면에 사용자 ID와 워크스페이스를 입력해 단기 개발 세션을
발급받을 수 있습니다. 운영 환경에서는 이 개발 세션 API가 비활성화되므로 OIDC 연동으로
발급된 Bearer 토큰을 **발급된 토큰으로 연결** 화면에 입력해야 합니다. 콘솔에서 실제 API를
통해 장치 등록·접근 회수, 원격 지원 요청 및 감사 로그 조회를 수행할 수 있습니다.
기본 SQLite 파일은 `g-one.db`이며 `G_ONE_DATABASE_URL`로 변경할 수 있습니다. 현재 구현은
장치 등록·폐기, tenant 범위 조회, 원격 지원 요청·동의·종료 및 감사 조회의 첫 수직
슬라이스입니다. 실제 배포 전에는 Authentik OIDC/JWKS 검증과 MariaDB 스키마 마이그레이션
체계를 완료해야 합니다.

### Docker Compose + MariaDB 배포

운영 환경은 MariaDB 11.4를 사용합니다. 최초 설치 스크립트는 JWT 및 DB 암호를 자동으로
생성하고, Compose 설정 검증, 이미지 준비, 웹 이미지 빌드와 서비스 시작까지 수행합니다.
스크립트를 다시 실행해도 기존 운영자 설정과 비밀은 덮어쓰지 않습니다.

```bash
python3 scripts/setup_server.py
```

기본 공개 포트는 호스트의 `127.0.0.1:8000`으로 제한됩니다. 외부 HTTPS 접근은 별도의
리버스 프록시에서 제공하고, 포트 변경이 필요하면 `.env`의 `G_ONE_HTTP_PORT`를 수정합니다.
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

## 문서 구조

```text
.
├── README.md                  # 프로젝트 소개와 빠른 시작
├── docs/
│   ├── PROJECT_DIRECTION.md                    # 제품 요구사항, 아키텍처, 보안, MVP와 의사결정 기록
│   └── WINDOWS_CLIENT_AND_SERVICE_REQUIREMENTS.md # Windows 앱·서비스 상세 요구사항
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
