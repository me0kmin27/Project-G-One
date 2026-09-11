# G-One Windows Client

.NET 8 WPF 기반 테스트베드 클라이언트입니다. 운영자가 배포 전에
`clientsettings.json`에 서버 URL과 워크스페이스를 지정하므로 사용자는 **계정과 암호만**
입력합니다. 액세스 토큰은 프로세스 메모리에만 유지합니다. 인증 후 서버 부트스트랩 API에서
장치 정책, WireGuard 프로필과 허가된 파일 공유 설정을 자동으로 받습니다.

## 모든 구성 요소를 포함한 MSI 만들기

GitHub Actions의 **Windows client MSI** 작업은 Windows x64용 `GOne.Client-x64.msi`를
만들고 **GOne.Client-MSI-win-x64** artifact로 제공합니다. MSI에는 self-contained .NET 8
클라이언트, 기본 설정과 공식 WireGuard 런타임 설치기가 모두 포함되므로 대상 PC에서 별도의
.NET 또는 VPN 프로그램을 준비할 필요가 없습니다.

Windows 개발 PC에서는 .NET 8 SDK와 인터넷 연결을 준비하고 다음 명령을 실행합니다.

```powershell
.\windows\publish.ps1
```

스크립트는 클라이언트를 self-contained single-file로 게시하고 공식 WireGuard 설치기를
내려받은 다음 WiX Toolset 프로젝트로 MSI를 만듭니다. WiX SDK는 `dotnet build`가 NuGet에서
자동 복원합니다. 결과 파일은 `windows\dist\win-x64\GOne.Client-x64.msi`입니다.

## 설치와 제거

MSI는 관리자 권한으로 다음 항목을 설치합니다.

- `%ProgramFiles%\G-One\GOne.Client.exe`와 `clientsettings.json`
- 시작 메뉴의 **G-One Client** 바로 가기
- 터널 관리에 필요한 공식 WireGuard Windows 런타임

대화형 설치는 MSI를 더블 클릭하고, 관리형 무인 배포는 다음과 같이 실행합니다.

```powershell
msiexec /i GOne.Client-x64.msi /qn
```

WireGuard 설치가 실패하면 MSI도 성공으로 처리되지 않습니다. 설치가 끝난 뒤에는 첫 로그인
때 별도 설치나 다운로드가 발생하지 않습니다. 클라이언트는 장치용 키를 등록해 `GOne`
터널을 연결하고 로그아웃하거나 창을 닫으면 터널 서비스를 제거합니다.

G-One Client는 **앱 및 기능** 또는 `msiexec /x GOne.Client-x64.msi`로 제거할 수 있습니다.
WireGuard는 다른 프로그램도 사용할 수 있는 공유 시스템 구성 요소이므로 클라이언트를
제거할 때 함께 제거하지 않습니다.
