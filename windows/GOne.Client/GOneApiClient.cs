using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;

namespace GOne.Client;

internal sealed class GOneApiClient(string serverUrl, string workspace) : IDisposable
{
    private readonly HttpClient http = new() { BaseAddress = new Uri(serverUrl.TrimEnd('/') + "/") };

    public async Task<Principal> LoginAsync(string subject, string password)
    {
        var response = await http.PostAsJsonAsync(
            "api/v1/session/login", new { subject, tenant_id = workspace, password });
        response.EnsureSuccessStatusCode();
        var token = await response.Content.ReadFromJsonAsync<SessionToken>()
            ?? throw new InvalidOperationException("로그인 토큰 응답이 비어 있습니다.");
        http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token.access_token);
        return await http.GetFromJsonAsync<Principal>("api/v1/me")
            ?? throw new InvalidOperationException("로그인 사용자 응답이 비어 있습니다.");
    }

    public async Task<ClientBootstrap> BootstrapAsync()
    {
        var response = await http.PostAsJsonAsync(
            "api/v1/client/bootstrap", new { device_name = Environment.MachineName });
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<ClientBootstrap>()
            ?? throw new InvalidOperationException("클라이언트 설정 응답이 비어 있습니다.");
    }

    public void Dispose() => http.Dispose();

    private sealed record SessionToken(string access_token);
}

internal sealed record Principal(string subject, string tenant_id, string[] roles);
internal sealed record ClientBootstrap(int version, UserPolicy user, VpnPolicy? vpn, string? vpn_profile, FileShare[] file_shares, Device device);
internal sealed record UserPolicy(string allowed_ips);
internal sealed record VpnPolicy(string address_cidr);
internal sealed record FileShare(string name, string unc_path);
internal sealed record Device(string name);
