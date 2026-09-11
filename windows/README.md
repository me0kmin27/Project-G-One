# G-One Windows Client

.NET 8 WPF 기반 테스트베드 클라이언트입니다. 운영자가 배포 전에 `clientsettings.json`에 서버 URL과 워크스페이스를 지정하므로 사용자는 **계정과 암호만** 입력합니다. 액세스 토큰은 프로세스 메모리에만 유지합니다. 클라이언트는 먼저 로그인을 완료하고, 인증된 뒤에만 서버 부트스트랩 API에서 장치 정책, WireGuard 프로필과 허가된 파일 공유 설정을 자동으로 받습니다.

## 바로 테스트할 EXE 만들기

GitHub Actions의 **Windows client executable** 작업이 Windows x64용 self-contained 패키지를 만들고 **GOne.Client-win-x64** artifact로 제공합니다. 대상 PC에는 .NET 설치가 필요 없습니다. Windows 개발 PC에서 같은 산출물을 만들려면 다음 명령을 실행합니다.

```powershell
.\windows\publish.ps1
```

실행 파일은 `windows\dist\win-x64\GOne.Client.exe`에 생성됩니다. 함께 생성된 `clientsettings.json`의 `serverUrl`과 `workspace`를 배포 환경에 맞게 수정하고 EXE와 같은 폴더에 둡니다.

Release 게시 설정(Windows x64, self-contained, single-file)은 프로젝트 파일에 포함되어 있어
IDE나 CI에서 아래 표준 명령을 직접 실행해도 같은 EXE를 만들 수 있습니다. 빌드 머신의 운영
체제와 관계없이 .NET 8 SDK가 필요합니다.

```console
dotnet publish windows/GOne.Client/GOne.Client.csproj -c Release -o windows/dist/win-x64
```

별도의 VPN 프로그램을 내려받거나 미리 설치할 필요가 없습니다. 게시 과정에서 공식
WireGuard 런타임 설치기를 `GOne.Client.exe` 안에 포함합니다. 첫 VPN 연결 때 런타임이 없는
PC에서만 내장 설치기를 꺼내 Windows 관리자 승인을 거쳐 자동 준비하고, 이어서 장치용 키를
등록해 `GOne` 터널을 즉시 연결합니다. 이후 로그인에는 설치 과정이 반복되지 않습니다.
로그아웃하거나 창을 닫으면 터널 서비스를 제거합니다.
