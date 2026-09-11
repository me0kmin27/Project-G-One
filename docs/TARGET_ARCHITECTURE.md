# Project G-One 목표 아키텍처 및 기술 제안

## 1. 제안 요약

단일 Debian 서버에서 운영 복잡도를 낮추면서 웹 침해가 VPN 호스트 권한으로 곧바로
확대되지 않도록 **모듈형 모놀리스 제어면 + 제한된 호스트 에이전트 + Windows UI/서비스**
구조를 제안한다.

| 계층 | 제안 기술 | 선택 이유 |
| --- | --- | --- |
| 서버 API | Python 3.12+, FastAPI, Pydantic, SQLAlchemy, Alembic | 기존 검증 자산을 활용하고 명시적 API 계약과 빠른 보안 테스트 가능 |
| 운영 DB | PostgreSQL | 제약, 트랜잭션, JSON, 동시성 및 감사 질의에 적합하고 AD와 독립적 |
| 서버 웹 | TypeScript, React, Vite | 관리자/사용자 포털을 타입 안전한 API 계약으로 분리 |
| 리버스 프록시 | Caddy | IP로 시작한 뒤 도메인·자동 TLS로 전환하기 쉬운 단순 운영 모델 |
| VPN | Debian 호스트 WireGuard + nftables | 커널 데이터면과 장치별 목적지 정책 강제, 컨테이너 네트워크 우회 감소 |
| 특권 적용기 | 작은 Python 호스트 서비스, Unix 소켓 | 허용된 WireGuard/nftables 작업만 수행하고 웹 프로세스와 권한 분리 |
| Windows | 현재 지원되는 .NET LTS, WPF UI + Windows Service | 웹에서 통합 배포하면서 네이티브 서비스/UAC/자격 증명 보호 가능 |
| 장치 키 저장 | Windows CNG/DPAPI, 가능하면 TPM 비내보내기 키 | 사용자 파일이나 로그에 장기 개인 키 저장 방지 |
| 배포 | Docker Compose(웹/API/DB) + systemd(VPN 적용기) | 단일 서버 재현성과 호스트 네트워크 권한의 명시적 분리 |

구현 착수 시점에는 Debian 안정 버전, Python 및 .NET LTS의 지원 수명을 공식 자료로 다시
검증하고 정확한 버전을 ADR에 고정한다. 버전 고정은 자동 업데이트가 아니라 테스트된
릴리스 단위로 수행한다.

## 2. 런타임 구성

```text
Internet
   │ HTTPS 443 / WireGuard UDP
   ▼
┌────────────────────── single Debian server ──────────────────────┐
│ Caddy ──► user web / admin web ──► unprivileged API              │
│    └────► authenticated Windows package download                  │
│                                      │                            │
│                                  PostgreSQL                       │
│                                      │ desired policy             │
│                                      ▼                            │
│                           Unix socket (strict command schema)      │
│                                      │                            │
│                     systemd privileged network agent              │
│                                      │                            │
│                           WireGuard + nftables                     │
└──────────────────────────────────────┼────────────────────────────┘
                                       │ routed, policy-filtered VPN
                                       ▼
                         internal SMB file server(s)
```

컨테이너에는 호스트 Docker 소켓을 제공하지 않는다. VPN 적용기는 API가 전달한 셸 문자열을
실행하지 않고 구조화된 정책을 검증하여 임시 파일에 렌더링하고, 구문 검사 후 원자적으로
적용한다. 마지막 정상 구성을 유지하여 API/DB 장애 중에도 기존 데이터면을 지속한다.

## 3. 네트워크와 파일 서버 제어

### 3.1 기본 흐름

1. 장치마다 고유 VPN 주소와 키를 할당한다.
2. 클라이언트는 분할 터널로 G-One 서버와 허용된 내부 CIDR만 라우팅한다.
3. nftables의 forwarding chain에서 소스 VPN IP별 목적지 IP·포트를 허용한다.
4. SMB는 기본적으로 파일 서버의 TCP 445만 허용하며 관리 포트는 별도 정책으로 둔다.
5. 파일 서버가 원래 클라이언트 VPN IP를 볼 수 있도록 내부망에 VPN 대역 반환 경로를
   구성하는 방식을 우선한다.
6. 반환 경로를 구성할 수 없는 환경만 SNAT를 선택하고, 파일 서버 감사의 주체 손실과
   보완 로그를 설치 마법사에서 명시한다.

### 3.2 이중 권한 경계

G-One의 정책은 네트워크 도달 가능성을 결정하고 파일 서버의 SMB ACL은 파일/폴더 권한을
결정한다. 두 경계가 모두 허용해야 접근된다. 초기 로컬 SMB 계정은 자격 증명 배포 위험이
크므로 AD 연동 환경에서는 Kerberos/도메인 그룹을 우선 검증하고, 비 AD 환경은 별도의
단기 자격 증명 브로커 기술 검증 후 구현한다.

## 4. 인증 및 AD/LDAP 확장

내부 모델은 `Identity`, `ExternalIdentity`, `Group`, `Role`, `Device`를 분리한다.

- 초기 설치: Argon2id 암호 해시를 사용하는 내장 관리자 및 사용자 계정
- 웹 SSO: OIDC 우선, 필요한 경우 AD FS/Authentik/Entra ID 등과 연결
- 디렉터리: 읽기 전용 LDAPS 동기화 어댑터와 명시적 그룹 매핑
- 장치: 사용자 토큰과 별도의 장치 키 쌍, 관리자 승인/폐기 및 짧은 인증서 또는 서명 토큰
- 세션: 짧은 액세스 세션, 회전되는 갱신 수단, 서버 측 폐기 상태

외부 디렉터리가 중단되어도 기존 관리자 비상 계정은 감사되는 복구 경로로 유지하되 일상
로그인에 사용하지 않는다. 디렉터리 삭제·비활성화는 정해진 시간 내 세션, VPN 정책과 장치
접근을 회수해야 한다.

## 5. 웹 애플리케이션 분리

- `/admin`: 관리자 전용 번들과 라우트, 역할·재인증 검사
- `/portal`: 일반 사용자용 장치, 연결 상태, 티켓 화면
- `/api/admin/v1`: 관리자 정책 API
- `/api/user/v1`: 본인 리소스와 동의 API
- `/api/agent/v1`: 장치 상호 인증 API
- `/api/downloads/v1`: 권한 검사, 일회 등록 코드 발급 및 Windows 패키지 다운로드

프런트엔드에서 메뉴를 숨기는 것은 보안 경계가 아니다. 각 API 핸들러와 서비스 계층에서
주체, 역할, 소유권 및 리소스 범위를 다시 검사한다. 관리자와 사용자 웹은 초기에는 같은
저장소와 배포 파이프라인을 공유하되 별도 진입점과 권한 테스트를 가진다.

## 6. Windows 구조

Windows 프로그램은 별도의 외부 배포 채널을 요구하지 않는다. 동일 저장소와 릴리스에서
서명된 범용 설치 파일을 한 번 생성하여 서버에 게시하고, 사용자는 G-One 웹을 통해서만
자신에게 할당된 배포 프로필과 함께 내려받는다. 사용자마다 바이너리를 다시 컴파일하지
않으므로 서명 검증과 업데이트가 단순하며, 사용자별 차이는 서버 정책으로 관리한다.

```text
GOne.Desktop (표준 사용자)
   └─ named pipe, ACL + mutual challenge
GOne.Agent Windows Service (LocalService 우선)
   ├─ device identity / policy cache
   ├─ WireGuard tunnel lifecycle
   ├─ SMB mapping lifecycle
   └─ remote-support session broker
```

설치·업데이트처럼 필요한 순간만 별도 상승 프로세스를 사용한다. 서비스와 UI 사이의 named
pipe는 현재 로그인한 사용자 SID와 요청 nonce를 검사한다. 정책 캐시는 서명, 대상 장치,
버전, 만료와 단조 증가 revision을 검증하며 만료 시 새 접근을 기본 거부한다.

원격 지원 데이터면은 프로토콜을 즉시 자체 구현하지 않는다. 먼저 검증용 어댑터에서
종단 간 암호화, 화면별 사용자 동의, Windows secure desktop 한계, NAT/VPN 경로, 라이선스,
무인 접근 차단과 세션 종료를 평가한 뒤 ADR로 선택한다.

### 6.1 관리자 배포 프로필

`ClientDeploymentProfile`은 VPN 정책, 허용 CIDR, 파일 서버/공유, 원격 지원 범위,
업데이트 채널과 대상 사용자·그룹을 참조한다. 설정 자체를 EXE에 영구 삽입하지 않고
revision이 있는 서버 정책으로 보관하여 관리자가 변경하거나 회수하면 다음 정책 갱신에
반영한다.

관리자 화면은 프로필의 생성·미리 보기·게시·회수, 대상별 다운로드 및 등록 상태를
제공한다. 사용자 포털은 현재 사용자에게 게시된 프로필만 표시한다. 다운로드 응답에는
콘텐츠 해시, 코드 서명 정보, 버전, 만료와 감사 상관관계 ID를 포함한다.

### 6.2 안전한 다운로드와 등록

```text
관리자: VPN/파일 서버/대상 선택 → 배포 프로필 게시
사용자: 웹 로그인 → 할당 프로필 선택 → 설치 번들 다운로드
설치기: 코드 서명 검증 → Windows 서비스 설치 → 장치 키를 로컬 생성
클라이언트: 1회 등록 코드 + 사용자 로그인 + 장치 공개키 제출
서버: 대상/만료/미사용 검증 → 장치 승인 → 현재 정책 발급
```

다운로드 URL은 인증과 권한 검사를 거치고 짧게 만료되며 재사용을 방지한다. 범용 설치
파일은 캐시할 수 있지만 사용자별 등록 manifest는 `Cache-Control: no-store`로 반환한다.
등록 코드는 해시만 서버에 저장하고 사용 즉시 폐기한다. 바이너리나 manifest에는 VPN
개인 키, SMB 암호, 사용자 토큰을 포함하지 않는다. 장치 키는 설치 후 해당 PC에서 생성한다.

## 7. 제안 디렉터리

```text
.
├── server/
│   ├── api/                 # FastAPI 진입점과 HTTP 계약
│   ├── domain/              # 정책과 상태 머신, 인프라 비의존
│   ├── application/         # 유스케이스와 권한 검사
│   ├── infrastructure/      # DB, 신원, WireGuard 적용기 클라이언트
│   ├── migrations/
│   └── tests/
├── web/
│   ├── admin/
│   ├── portal/
│   └── shared/
├── client-windows/
│   ├── src/GOne.Desktop/
│   ├── src/GOne.Agent/
│   ├── src/GOne.Contracts/
│   ├── tests/
│   └── installer/
├── artifacts/                # CI가 만든 서명된 클라이언트 릴리스 메타데이터
├── network-agent/           # Debian systemd 특권 적용기
├── deploy/
│   ├── compose/
│   ├── systemd/
│   └── caddy/
├── docs/
│   ├── adr/
│   ├── operations/
│   └── security/
├── scripts/                 # install, update, backup, restore, doctor
└── tests/                   # 계약, 통합, 네트워크 격리 E2E
```

## 8. 운영 경험

운영자는 `g-one` 관리 명령 하나만 사용한다.

- `g-one install`: 사전 점검, 비밀 생성, DB, 서비스, 초기 관리자 설정
- `g-one configure-domain`: DNS 확인, Caddy 설정 검증, TLS 전환
- `g-one add-file-server`: 경로·TCP 445·인증 방식과 반환 라우트 검사
- `g-one publish-client`: 서명·해시를 검증한 Windows 릴리스를 웹 다운로드에 게시
- `g-one doctor`: 컨테이너, DB, 인증서, WireGuard, forwarding, 파일 서버 연결 검사
- `g-one backup` / `restore`: DB, 구성, 암호화된 비밀과 복구 검증
- `g-one update` / `rollback`: 서명된 릴리스, 사전 백업, 마이그레이션과 상태 확인

설치기는 파괴적 동작 전에 계획을 출력하고, 반복 실행해도 비밀이나 정상 구성을 덮어쓰지
않는다. Docker가 없어도 설치 안내가 명확해야 하며 Docker/Compose 세부 명령은 장애 진단
부록에서만 요구한다.

## 9. 구현 게이트

1. 요구사항 기준선 승인
2. 위협 모델 갱신 및 VPN→내부 파일 서버 데이터 흐름 검토
3. 서버/Windows/다운로드 등록/네트워크 적용기 API 계약 승인
4. 새 디렉터리 골격과 CI만 생성
5. 인증·배포 프로필·웹 다운로드·장치 등록 수직 슬라이스
6. VPN과 nftables 격리 시험
7. SMB 연결·회수 및 AD/비 AD 인증 기술 검증
8. 원격 지원 기술 검증과 별도 승인
9. 백업·복구·업데이트 훈련 후 운영 후보 지정

각 게이트는 수용 기준, 자동화 테스트와 작업 기록이 없으면 완료로 표시하지 않는다.
