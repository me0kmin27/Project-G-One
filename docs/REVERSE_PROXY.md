# 리버스 프록시 외부 접속 가이드

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
