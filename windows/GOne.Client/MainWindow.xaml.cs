using System.IO;
using System.Text.Json;
using System.Windows;

namespace GOne.Client;

public partial class MainWindow : Window
{
    private readonly ClientSettings settings;
    private readonly WindowsConnectionManager connections = new();
    private GOneApiClient? api;

    public MainWindow()
    {
        InitializeComponent();
        settings = JsonSerializer.Deserialize<ClientSettings>(
            File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "clientsettings.json")))
            ?? throw new InvalidOperationException("clientsettings.json을 읽을 수 없습니다.");
    }

    private async void Login_Click(object sender, RoutedEventArgs e)
    {
        LoginButton.IsEnabled = false;
        LoginError.Text = "";
        try
        {
            api?.Dispose();
            api = new GOneApiClient(settings.serverUrl, settings.workspace);

            // Authentication is deliberately completed before any device configuration request.
            var principal = await api.LoginAsync(SubjectBox.Text, PasswordBox.Password);
            ShowAuthenticatedSession(principal);
            await ConfigureDeviceAsync();
        }
        catch (Exception ex)
        {
            api?.Dispose();
            api = null;
            LoginError.Text = $"로그인 실패: {ex.Message}";
        }
        finally
        {
            LoginButton.IsEnabled = true;
        }
    }

    private void ShowAuthenticatedSession(Principal principal)
    {
        WelcomeText.Text = $"{principal.subject} · {principal.tenant_id}";
        PasswordBox.Clear();
        LoginPanel.Visibility = Visibility.Collapsed;
        DashboardPanel.Visibility = Visibility.Visible;
        ConnectionText.Text = "● 로그인됨 · 서버 설정 요청 중";
    }

    private async Task ConfigureDeviceAsync()
    {
        try
        {
            var bootstrap = await api!.BootstrapAsync();
            DevicesList.ItemsSource = new[] { bootstrap.device };
            PolicyText.Text = $"정책 v{bootstrap.version} · 경로 {bootstrap.user.allowed_ips}";
            ConnectionText.Text = $"● 로그인됨 · {await connections.ApplyAsync(bootstrap)}";
        }
        catch (Exception ex)
        {
            ConnectionText.Text = $"● 로그인됨 · 자동 설정 실패: {ex.Message}";
        }
    }

    private async void Logout_Click(object sender, RoutedEventArgs e)
    {
        await connections.ClearAsync();
        api?.Dispose();
        api = null;
        DevicesList.ItemsSource = null;
        DashboardPanel.Visibility = Visibility.Collapsed;
        LoginPanel.Visibility = Visibility.Visible;
    }

    protected override void OnClosed(EventArgs e)
    {
        connections.ClearAsync().GetAwaiter().GetResult();
        api?.Dispose();
        base.OnClosed(e);
    }

    private sealed record ClientSettings(string serverUrl, string workspace);
}
