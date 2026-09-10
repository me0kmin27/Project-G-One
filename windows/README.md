# G-One Windows Client

.NET 8 WPF 기반 테스트베드 클라이언트입니다. 서버 URL, 사용자, 워크스페이스와 암호를 매 실행마다 입력하며 액세스 토큰은 프로세스 메모리에만 유지됩니다.

```powershell
dotnet build .\windows\GOne.Client\GOne.Client.csproj
dotnet run --project .\windows\GOne.Client\GOne.Client.csproj
```

현재 수직 슬라이스는 대화형 로그인, 서버 인증, 사용자 장치 조회, 명시적 로그아웃 시 메모리 세션 정리를 제공합니다. WireGuard/SMB 시스템 변경은 향후 권한 분리 Windows Service와 서명된 정책 IPC가 준비된 뒤 연결하며 UI 프로세스에서 관리자 명령을 직접 실행하지 않습니다.
