# 리버스 프록시 외부 접속 가이드

## 처음 설치: 순서대로 실행

다음 순서를 바꾸지 마십시오. 명령의 `G_ONE_SERVER_IP`, 도메인 및 프록시 서버 IP는 실제
값으로 바꿔야 합니다.

### 1. G-One 서버에서 설치 및 기동

저장소 디렉터리에서 아래 **한 줄**을 실행합니다. 이 명령 하나가 환경 파일 생성, MariaDB
이미지 준비, 웹 빌드, 컨테이너 기동과 로컬 연결 점검을 모두 수행합니다.

```bash
cd /path/to/Project-G-One && python3 scripts/setup_server.py
```

마지막 출력에 `[ OK ]` 세 개와 `All local checks passed`가 표시되어야 합니다. 실패하면
바로 로그를 확인합니다.

```bash
cd /path/to/Project-G-One && python3 scripts/manage_server.py logs
```

### 권한 오류가 표시되는 경우

설치 스크립트는 Docker 소켓에 일반 사용자로 접근할 수 없으면 Docker 명령에만 자동으로
`sudo`를 적용합니다. 프로젝트 파일 자체가 root 소유라면 출력된 `chown` 명령을 한 번
실행한 뒤 설치 명령을 다시 실행하십시오. Docker 그룹을 영구적으로 적용하고 싶다면 다음
한 줄을 실행하고 **로그아웃 후 다시 로그인**합니다.

```bash
sudo usermod -aG docker "$USER"
```

중요: `sudo python3 scripts/setup_server.py`를 실행하지 마십시오. 그렇게 하면 `.env`가 root
소유가 되어 다음 업데이트에서 다시 권한 오류가 발생할 수 있습니다. 설치기는 권한 상승이
필요한 Docker 명령만 제한적으로 `sudo`로 실행합니다.

### 2. 프록시의 위치에 맞춰 바인딩

Nginx/Caddy가 **G-One과 같은 서버**에 있다면 아래 한 줄을 실행합니다.

```bash
cd /path/to/Project-G-One && python3 scripts/configure_server.py set http-bind 127.0.0.1 && python3 scripts/manage_server.py restart && python3 scripts/manage_server.py doctor
```

Nginx/Caddy가 **다른 서버**에 있다면 아래 한 줄을 실행합니다.

```bash
cd /path/to/Project-G-One && python3 scripts/configure_server.py set http-bind 0.0.0.0 && python3 scripts/manage_server.py restart && python3 scripts/manage_server.py doctor
```

다른 서버에서 프록시할 때는 G-One 서버 방화벽의 TCP 8000을 **프록시 서버 IP에만**
허용합니다. 일반 인터넷 전체에는 8000 포트를 공개하지 마십시오.

### 3. 프록시 upstream 설정

- 같은 서버: `http://127.0.0.1:8000`
- 다른 서버: `http://G_ONE_SERVER_IP:8000`

아래의 Nginx 또는 Caddy 예시를 적용한 뒤 설정을 다시 불러옵니다. HTTPS 주소에 `/healthz`
를 붙여 `{"status":"ok"}` 응답이 나오면 연결이 완료된 것입니다.

### 4. 브라우저에서 사용

1. `https://g-one.example.com/`을 엽니다.
2. 사용자 ID와 워크스페이스 ID를 입력합니다.
3. G-One 서버의 `.env`에 생성된 `G_ONE_CONSOLE_PASSWORD` 값을 입력합니다. 화면에 암호를
   출력하지 않고 설정 여부만 확인하려면 `python3 scripts/configure_server.py show`를 사용합니다.
4. 로그인 후 **장치 → 장치 등록**에서 첫 장치를 등록합니다.
5. **원격 지원 → 지원 요청**에서 장치와 권한을 선택해 사용자 동의를 요청합니다.
6. **감사 로그**에서 장치 등록과 지원 요청 이력을 확인합니다.

## 502 Bad Gateway 즉시 진단

G-One 서버에서 아래 **한 줄**을 실행하십시오.

```bash
cd /path/to/Project-G-One && python3 scripts/manage_server.py doctor
```

- `1/3`에서 실패: Docker 또는 Compose 문제입니다.
- `2/3`에서 실패: 웹/DB 컨테이너가 준비되지 않았습니다. `python3 scripts/manage_server.py logs`를 실행합니다.
- 모든 로컬 검사가 통과하지만 502가 계속됨: 프록시의 upstream 주소, G-One 서버 방화벽,
  두 서버 사이의 라우팅 순서로 확인합니다.

프록시가 다른 서버에 있을 때는 **그 프록시 서버에서** 아래 한 줄도 실행합니다.

```bash
curl -fsS http://G_ONE_SERVER_IP:8000/healthz && echo 'G-One upstream OK'
```

이 명령이 실패하면 리버스 프록시 설정을 변경하기 전에 IP, TCP 8000 방화벽과
`G_ONE_HTTP_BIND=0.0.0.0` 설정부터 수정해야 합니다.

### `address already in use`가 표시되는 경우

이 메시지는 권한 오류가 아니라 호스트의 HTTP 포트(기본 8000)를 다른 컨테이너 또는
프로세스가 이미 사용한다는 뜻입니다. 배포 스크립트는 이제 기동 전에 포트를 검사하고,
이전 배포에서 남은 `g-one-web` 컨테이너 또는 `g_one.main:app`을 실행하던 레거시 Uvicorn
프로세스만 안전하게 종료한 뒤 새 컨테이너를 시작합니다.
관련 없는 컨테이너나 호스트 프로세스가 포트를 점유한 경우에는 임의로 종료하지 않고
점유 주체와 포트 변경 명령을 출력합니다.

수동 재배포도 다음 한 줄이면 동일한 사전 점검을 거칩니다.

```bash
cd /path/to/Project-G-One && python3 scripts/manage_server.py start
```

다른 서비스가 의도적으로 8000 포트를 사용한다면 다음 한 줄로 G-One을 8001로 변경해
재시작합니다. 이 경우 리버스 프록시 upstream도 반드시 `http://G_ONE_SERVER_IP:8001`로
변경해야 합니다.

```bash
cd /path/to/Project-G-One && python3 scripts/configure_server.py set http-port 8001 && python3 scripts/manage_server.py start
```

## 문제 판단

기존 Compose 설정은 웹 컨테이너 포트를 `127.0.0.1:8000`에만 게시했습니다. 따라서
G-One과 같은 호스트의 Nginx/Caddy는 접속할 수 있지만, **다른 서버에서 실행되는 리버스
프록시는 G-One 서버의 8000 포트에 접속할 수 없었습니다.** 또한 운영 모드에서는 이전
개발 세션 API가 비활성화되어 페이지가 표시되어도 콘솔 로그인을 완료할 수 없었습니다.

현재 설정은 다음 두 문제를 모두 해결합니다.

- 기본 바인딩을 `0.0.0.0:8000`으로 변경해 별도 프록시 서버에서 접근할 수 있습니다.
- 설치 시 생성되는 `G_ONE_CONSOLE_PASSWORD`로 운영 콘솔 세션을 발급합니다.

## 네트워크 구성

G-One 서버의 방화벽에서 TCP 8000은 리버스 프록시 서버 IP에만 허용하십시오. 인터넷에
8000 포트를 직접 공개하면 안 됩니다. 리버스 프록시에서는 공인 443 포트를 제공하고
`http://G_ONE_SERVER_IP:8000`을 upstream으로 사용합니다.

프록시가 G-One과 같은 호스트에 있다면 공격 표면을 줄이기 위해 다음을 실행하십시오.

```bash
python3 scripts/configure_server.py set http-bind 127.0.0.1
python3 scripts/manage_server.py restart
```

프록시가 별도 호스트에 있다면 기본값을 유지하거나 명시적으로 설정합니다.

```bash
python3 scripts/configure_server.py set http-bind 0.0.0.0
python3 scripts/manage_server.py restart
```

## Nginx 예시

```nginx
server {
    listen 443 ssl http2;
    server_name g-one.example.com;

    ssl_certificate     /etc/letsencrypt/live/g-one.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/g-one.example.com/privkey.pem;

    location / {
        proxy_pass http://G_ONE_SERVER_IP:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

G-One은 루트 경로(`/`) 기준으로 정적 자산과 API를 제공하므로 하위 경로가 아닌 별도
호스트 이름으로 프록시하는 구성을 권장합니다.

## Caddy 예시

```caddyfile
g-one.example.com {
    reverse_proxy G_ONE_SERVER_IP:8000
}
```

## 점검 순서

G-One 서버에서 컨테이너와 로컬 응답을 먼저 확인합니다.

```bash
python3 scripts/manage_server.py status
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
```

별도 프록시 서버에서는 upstream 연결을 확인합니다.

```bash
curl -fsS http://G_ONE_SERVER_IP:8000/healthz
```

마지막으로 외부 클라이언트에서 HTTPS와 정적 자산을 확인합니다.

```bash
curl -fsS https://g-one.example.com/healthz
curl -fsSI https://g-one.example.com/assets/app.js
```

첫 번째 단계만 실패하면 G-One 컨테이너 문제이고, 두 번째 단계만 실패하면 바인딩 또는
방화벽 문제입니다. 앞의 단계는 성공하지만 마지막 단계가 실패하면 DNS, TLS 인증서 또는
리버스 프록시 설정 문제입니다.
