namespace GOne.Client;

internal sealed class WindowsConnectionManager
{
    private readonly WindowsVpnManager vpn = new();

    public async Task<string> ApplyAsync(ClientBootstrap settings)
    {
        if (string.IsNullOrWhiteSpace(settings.vpn_profile))
            return settings.vpn is null ? "VPN 정책이 구성되지 않았습니다." : "사용자 VPN 주소 또는 서버 키가 없습니다.";

        await vpn.ConnectAsync(settings.vpn_profile);
        return settings.file_shares.Length == 0
            ? "VPN 연결됨 · 허가된 파일 공유 없음"
            : $"VPN 연결됨 · 파일 공유 {settings.file_shares.Length}개 설정 수신";
    }

    public Task ClearAsync() => vpn.DisconnectAsync();
}
