using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Windows;

namespace GOne.Client;

public partial class MainWindow : Window
{
    private HttpClient? client;
    private string? accessToken; // Deliberately memory-only; never persisted.

    public MainWindow() => InitializeComponent();

    private async void Login_Click(object sender, RoutedEventArgs e)
    {
        LoginButton.IsEnabled = false;
        LoginError.Text = "";
        try
        {
            client?.Dispose();
            client = new HttpClient { BaseAddress = new Uri(ServerBox.Text.Trim().TrimEnd('/') + "/") };
            var response = await client.PostAsJsonAsync("api/v1/session/console", new { subject = SubjectBox.Text, tenant_id = TenantBox.Text, password = PasswordBox.Password });
            response.EnsureSuccessStatusCode();
            accessToken = (await response.Content.ReadFromJsonAsync<SessionToken>())!.access_token;
            client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", accessToken);
            var me = await client.GetFromJsonAsync<Principal>("api/v1/me");
            var devices = await client.GetFromJsonAsync<JsonElement[]>("api/v1/devices") ?? [];
            DevicesList.ItemsSource = devices.Select(item => new { name = item.GetProperty("name").GetString() });
            WelcomeText.Text = $"{me!.subject} · {me.tenant_id}";
            PasswordBox.Clear();
            LoginPanel.Visibility = Visibility.Collapsed;
            DashboardPanel.Visibility = Visibility.Visible;
        }
        catch (Exception ex) { LoginError.Text = $"연결 실패: {ex.Message}"; }
        finally { LoginButton.IsEnabled = true; }
    }

    private void Logout_Click(object sender, RoutedEventArgs e)
    {
        accessToken = null;
        client?.Dispose(); client = null;
        DevicesList.ItemsSource = null;
        DashboardPanel.Visibility = Visibility.Collapsed;
        LoginPanel.Visibility = Visibility.Visible;
    }

    protected override void OnClosed(EventArgs e) { accessToken = null; client?.Dispose(); base.OnClosed(e); }
    private sealed record SessionToken(string access_token);
    private sealed record Principal(string subject, string tenant_id, string[] roles);
}
