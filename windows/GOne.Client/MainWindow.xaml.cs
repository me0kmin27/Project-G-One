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

    public MainWindow()
    {
        InitializeComponent();
        settings = JsonSerializer.Deserialize<ClientSettings>(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "clientsettings.json")));
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
            PasswordBox.Clear();
            LoginPanel.Visibility = Visibility.Collapsed;
            DashboardPanel.Visibility = Visibility.Visible;
            await SynchronizePolicy();
            policyTimer.Start();
        }
        catch (Exception ex) { LoginError.Text = $"연결 실패: {ex.Message}"; }
        finally { LoginButton.IsEnabled = true; }
    }

    private void Logout_Click(object sender, RoutedEventArgs e)
    {
        policyTimer.Stop();
        accessToken = null;
        client?.Dispose(); client = null;
        DevicesList.ItemsSource = null;
        DashboardPanel.Visibility = Visibility.Collapsed;
        LoginPanel.Visibility = Visibility.Visible;
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
            ConnectionText.Text = "● 정책 최신 상태";
        }
        catch (Exception ex) { ConnectionText.Text = $"● 동기화 재시도 예정: {ex.Message}"; }
    }

    protected override void OnClosed(EventArgs e) { policyTimer.Stop(); accessToken = null; client?.Dispose(); base.OnClosed(e); }
    private sealed record SessionToken(string access_token);
    private sealed record Principal(string subject, string tenant_id, string[] roles);
    private sealed record ClientSettings(string serverUrl, string workspace);
    private sealed record ClientPolicy(int version, UserPolicy user, VpnPolicy? vpn, Device[] devices);
    private sealed record UserPolicy(string allowed_ips);
    private sealed record VpnPolicy(string address_cidr);
    private sealed record Device(string name);
}
