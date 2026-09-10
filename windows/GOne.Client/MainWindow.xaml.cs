using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;

namespace GOne.Client;

public partial class MainWindow : Window
{
    private HttpClient? client;
    private string? accessToken; // Deliberately memory-only; never persisted.
    private readonly DispatcherTimer policyTimer = new();
    private ClientSettings? settings;
    private WindowsVpnManager? vpn;

    public MainWindow()
    {
        InitializeComponent();
        settings = JsonSerializer.Deserialize<ClientSettings>(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "clientsettings.json")));
        vpn = new WindowsVpnManager(settings!.wireguardPath);
        policyTimer.Interval = TimeSpan.FromSeconds(15);
        policyTimer.Tick += async (_, _) => await SynchronizePolicy();
    }

    private async void Login_Click(object sender, RoutedEventArgs e)
    {
        LoginButton.IsEnabled = false;
        LoginError.Text = "";
        try
        {
            client?.Dispose();
            client = new HttpClient { BaseAddress = new Uri(settings!.serverUrl.TrimEnd('/') + "/") };
            var response = await client.PostAsJsonAsync("api/v1/session/login", new { subject = SubjectBox.Text, tenant_id = settings.workspace, password = PasswordBox.Password });
            response.EnsureSuccessStatusCode();
            accessToken = (await response.Content.ReadFromJsonAsync<SessionToken>())!.access_token;
            client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", accessToken);
            var me = await client.GetFromJsonAsync<Principal>("api/v1/me");
            WelcomeText.Text = $"{me!.subject} · {me.tenant_id}";
            await SynchronizePolicy();
            await ConnectVpn();
            PasswordBox.Clear();
            LoginPanel.Visibility = Visibility.Collapsed;
            DashboardPanel.Visibility = Visibility.Visible;
            policyTimer.Start();
        }
        catch (Exception ex)
        {
            policyTimer.Stop();
            if (vpn is not null) await vpn.DisconnectAsync();
            accessToken = null;
            client?.Dispose(); client = null;
            LoginError.Text = $"연결 실패: {ex.Message}";
        }
        finally { LoginButton.IsEnabled = true; }
    }

    private async void Logout_Click(object sender, RoutedEventArgs e)
    {
        policyTimer.Stop();
        if (vpn is not null) await vpn.DisconnectAsync();
        accessToken = null;
        client?.Dispose(); client = null;
        DevicesList.ItemsSource = null;
        DashboardPanel.Visibility = Visibility.Collapsed;
        LoginPanel.Visibility = Visibility.Visible;
    }

    private async Task ConnectVpn()
    {
        ConnectionText.Text = "● VPN 구성 중";
        var response = await client!.PostAsJsonAsync("api/v1/client/vpn/enroll", new { device_name = Environment.MachineName });
        response.EnsureSuccessStatusCode();
        var enrollment = await response.Content.ReadFromJsonAsync<VpnEnrollment>();
        if (string.IsNullOrWhiteSpace(enrollment?.client_config))
            throw new InvalidOperationException("서버가 WireGuard 구성을 반환하지 않았습니다.");
        await vpn!.ConnectAsync(enrollment.client_config);
        ConnectionText.Text = "● VPN 연결됨";
    }

    private async Task SynchronizePolicy()
    {
        if (client is null) return;
        try
        {
            var policy = await client.GetFromJsonAsync<ClientPolicy>("api/v1/client/policy");
            if (policy is null) return;
            if (!policy.devices.Any(device => device.name.Equals(Environment.MachineName, StringComparison.OrdinalIgnoreCase)))
            {
                await client.PostAsJsonAsync("api/v1/devices", new { name = Environment.MachineName });
                policy = await client.GetFromJsonAsync<ClientPolicy>("api/v1/client/policy");
            }
            DevicesList.ItemsSource = policy?.devices;
            PolicyText.Text = policy?.vpn is null
                ? $"정책 v{policy?.version} · VPN 미구성 · 다음 확인 15초 이내"
                : $"정책 v{policy.version} · {policy.vpn.address_cidr} · 경로 {policy.user.allowed_ips} · 다음 확인 15초 이내";
            ConnectionText.Text = policy?.vpn is null ? "● VPN 미구성" : "● VPN 연결됨 · 정책 최신 상태";
        }
        catch (Exception ex) { ConnectionText.Text = $"● 동기화 재시도 예정: {ex.Message}"; }
    }

    protected override void OnClosed(EventArgs e) { policyTimer.Stop(); vpn?.DisconnectAsync().GetAwaiter().GetResult(); accessToken = null; client?.Dispose(); base.OnClosed(e); }
    private sealed record SessionToken(string access_token);
    private sealed record Principal(string subject, string tenant_id, string[] roles);
    private sealed record ClientSettings(string serverUrl, string workspace, string wireguardPath);
    private sealed record VpnEnrollment(string? client_config);
    private sealed record ClientPolicy(int version, UserPolicy user, VpnPolicy? vpn, Device[] devices);
    private sealed record UserPolicy(string allowed_ips);
    private sealed record VpnPolicy(string address_cidr);
    private sealed record Device(string name);
}
