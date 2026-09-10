using System.Diagnostics;
using System.IO;

namespace GOne.Client;

internal sealed class WindowsVpnManager(string wireGuardPath)
{
    private const string TunnelName = "GOne";

    public async Task ConnectAsync(string configuration)
    {
        if (!OperatingSystem.IsWindows())
            throw new PlatformNotSupportedException("VPN 연결은 Windows에서만 지원됩니다.");
        if (!File.Exists(wireGuardPath))
            throw new FileNotFoundException("WireGuard가 설치되어 있지 않습니다.", wireGuardPath);

        var directory = Path.Combine(Path.GetTempPath(), "GOne");
        Directory.CreateDirectory(directory);
        var configPath = Path.Combine(directory, $"{TunnelName}.conf");
        await File.WriteAllTextAsync(configPath, configuration);
        try
        {
            await RunAsync($"/uninstalltunnelservice {TunnelName}", tolerateFailure: true);
            await RunAsync($"/installtunnelservice \"{configPath}\"");
        }
        finally
        {
            File.Delete(configPath);
        }
    }

    public Task DisconnectAsync() => OperatingSystem.IsWindows() && File.Exists(wireGuardPath)
        ? RunAsync($"/uninstalltunnelservice {TunnelName}", tolerateFailure: true)
        : Task.CompletedTask;

    private async Task RunAsync(string arguments, bool tolerateFailure = false)
    {
        using var process = Process.Start(new ProcessStartInfo(wireGuardPath, arguments)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardError = true,
        }) ?? throw new InvalidOperationException("WireGuard 프로세스를 시작할 수 없습니다.");
        var error = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        if (!tolerateFailure && process.ExitCode != 0)
            throw new InvalidOperationException($"WireGuard 연결 실패 ({process.ExitCode}): {error}".Trim());
    }
}
