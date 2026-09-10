# G-One Windows Client

.NET 8 WPF 기반 테스트베드 클라이언트입니다. 운영자가 배포 전에 `clientsettings.json`에 서버 URL과 워크스페이스를 지정하므로 사용자는 **계정과 암호만** 입력합니다. 액세스 토큰은 프로세스 메모리에만 유지되며 클라이언트는 15초마다 서버 정책을 다시 조회해 장치, VPN 프로필과 라우팅 변경을 반영합니다.

## 바로 테스트할 EXE 만들기

GitHub Actions의 **Windows client executable** 작업이 Windows x64용 self-contained 패키지를 만들고 **GOne.Client-win-x64** artifact로 제공합니다. 대상 PC에는 .NET 설치가 필요 없습니다. Windows 개발 PC에서 같은 산출물을 만들려면 다음 명령을 실행합니다.

```powershell
.\windows\publish.ps1
```

실행 파일은 `windows\dist\win-x64\GOne.Client.exe`에 생성됩니다. 함께 생성된 `clientsettings.json`의 `serverUrl`과 `workspace`를 배포 환경에 맞게 수정하고 EXE와 같은 폴더에 둡니다.

현재 수직 슬라이스는 계정 로그인, 자동 장치 등록, 서버 정책 주기 동기화, VPN 주소·라우팅 표시와 명시적 로그아웃 시 메모리 세션 정리를 제공합니다. 실제 WireGuard/SMB 시스템 변경은 권한 분리 Windows Service와 서명된 정책 IPC가 준비된 뒤 연결하며 UI 프로세스에서 관리자 명령을 직접 실행하지 않습니다.
