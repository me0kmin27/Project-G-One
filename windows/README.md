# G-One Windows Client MSI

.NET 8 WPF 클라이언트와 공식 WireGuard for Windows 런타임 설치 관리자를 하나의 x64 MSI에
담습니다. WireGuard 구성 요소는 프로젝트가 임의로 재구현한 바이너리가 아니라
[WireGuard 공식 저장소](https://www.wireguard.com/repositories/)가 안내하는 Windows 배포물
(`https://download.wireguard.com/windows-client/wireguard-installer.exe`)을 빌드 시 받아
포함합니다. 서버 컨테이너는 Debian 저장소의 `wireguard-tools`를 사용합니다.

## MSI 빌드

Windows 개발 PC에서 .NET 8 SDK로 다음 명령을 실행합니다. 스크립트는 self-contained x64
앱을 게시하고, 공식 WireGuard 설치 관리자를 내려받은 뒤 WiX Toolset으로 MSI를 만듭니다.

```powershell
.\windows\publish.ps1
```

결과는 `windows\dist\win-x64\GOne.Client.msi`입니다. CI artifact 이름은
`GOne.Client-msi-win-x64`입니다. MSI는 다음 항목을 모두 설치합니다.

- .NET 런타임을 별도로 요구하지 않는 G-One 클라이언트
- 배포 기본값인 `clientsettings.json`
- 최초 연결 시 필요한 경우 관리자 승인으로 실행되는 공식 WireGuard 설치 관리자
- 시작 메뉴 바로 가기와 사용자 로그인 시 자동 실행 등록

MSI 설치/제거와 로그 수집은 표준 Windows Installer 명령으로 수행할 수 있습니다.

```powershell
msiexec /i GOne.Client.msi /qn /l*v GOne-install.log
msiexec /x GOne.Client.msi /qn /l*v GOne-uninstall.log
```

## 설치 및 연결 수명 주기

MSI가 클라이언트를 Program Files에 설치하고 사용자 로그인 자동 실행을 등록하므로 매번
압축을 풀거나 EXE 위치를 관리할 필요가 없습니다. 인증 후 받은 장치 전용 설정은 WireGuard
터널 서비스 `GOne`으로 등록됩니다. 보안상 명시적 로그아웃 또는 앱 종료 시 터널 서비스를
정리하며, 다음 로그인 때 정책을 다시 받아 연결합니다. 개인 키가 든 임시 구성 파일은 서비스
등록 직후 삭제됩니다.

웹에서 내려받는 배포 ZIP에는 MSI와 10분 유효 등록 manifest만 들어가며 사용자 암호,
SMB 암호 또는 WireGuard 개인 키는 포함하지 않습니다. `clientsettings.json`의 서버 URL과
워크스페이스 기본값은 배포 환경에 맞게 MSI 빌드 전에 지정합니다.
