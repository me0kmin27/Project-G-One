# G-One Windows Client

.NET 8 WPF 기반 테스트베드 클라이언트입니다. 운영자가 배포 전에
`clientsettings.json`에 서버 URL과 워크스페이스를 지정하므로 사용자는 **계정과 암호만**
입력합니다. 액세스 토큰은 프로세스 메모리에만 유지합니다. 인증 후 서버 부트스트랩 API에서
장치 정책, WireGuard 프로필과 허가된 파일 공유 설정을 자동으로 받습니다.

## 모든 구성 요소를 포함한 MSI 만들기

GitHub Actions의 **Windows client MSI** 작업은 Windows x64용 `GOne.Client-x64.msi`를
만들고 **GOne.Client-MSI-win-x64** artifact로 제공합니다. MSI에는 self-contained .NET 8
클라이언트, 기본 설정과 G-One 전용 WireGuard 런타임이 모두 포함되므로 대상 PC에서 별도의
.NET 또는 WireGuard 프로그램을 설치할 필요가 없습니다. WireGuard 제품 설치기를 MSI 안에서
다시 실행하지 않습니다.

Windows 개발 PC에서는 .NET 8 SDK와 인터넷 연결을 준비하고 다음 명령을 실행합니다.

```powershell
.\windows\publish.ps1
```

스크립트는 클라이언트를 self-contained single-file로 게시하고 고정 버전의 공식 WireGuard
MSI에서 실행 파일만 관리 이미지로 추출한 다음 WiX Toolset 프로젝트로 하나의 MSI를 만듭니다.
WireGuard MSI를 설치하지는 않습니다. WiX SDK는 `dotnet build`가 NuGet에서
자동 복원합니다. 결과 파일은 `windows\dist\win-x64\GOne.Client-x64.msi`입니다.

## 설치와 제거

MSI는 관리자 권한으로 다음 항목을 설치합니다.

- `%ProgramFiles%\G-One\GOne.Client.exe`와 `clientsettings.json`
- 시작 메뉴의 **G-One Client** 바로 가기
- `%ProgramFiles%\G-One\Vpn`의 G-One 전용 WireGuard Windows 런타임

대화형 설치는 MSI를 더블 클릭하고, 관리형 무인 배포는 다음과 같이 실행합니다.

```powershell
msiexec /i GOne.Client-x64.msi /qn
```

중첩된 WireGuard 설치 단계가 없으므로 해당 설치기의 오류 때문에 G-One 설치가 중간에
중단되지 않습니다. 설치가 끝난 뒤에는 첫 로그인 때 별도 설치나 다운로드가 발생하지
않습니다. 클라이언트는 함께 설치된 전용 런타임으로 장치용 키를 등록해 `GOne`
터널을 연결하고 로그아웃하거나 창을 닫으면 터널 서비스를 제거합니다.

G-One Client는 **앱 및 기능** 또는 `msiexec /x GOne.Client-x64.msi`로 제거할 수 있습니다.
전용 VPN 런타임도 G-One Client의 구성 요소이므로 함께 제거됩니다. PC에 별도로 설치된
WireGuard가 있다면 G-One은 그 프로그램이나 설정을 사용하거나 변경하지 않습니다.
