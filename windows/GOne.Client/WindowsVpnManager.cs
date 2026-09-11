using System.Diagnostics;
using System.IO;

namespace GOne.Client;

internal sealed class WindowsVpnManager
{
    private const string TunnelName = "GOne";
    // G-One ships a private copy of the official runtime. Do not depend on, or
    // modify, a separately installed WireGuard desktop application.
    private static readonly string WireGuardPath = Path.Combine(
        AppContext.BaseDirectory, "Vpn", "wireguard.exe");

    public async Task ConnectAsync(string configuration)
    {
        if (!OperatingSystem.IsWindows())
            throw new PlatformNotSupportedException("VPN 연결은 Windows에서만 지원됩니다.");
        if (!File.Exists(WireGuardPath))
            throw new InvalidOperationException(
                "G-One VPN 구성 요소를 찾을 수 없습니다. G-One Client를 복구하거나 다시 설치하십시오.");

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

    public Task DisconnectAsync() => OperatingSystem.IsWindows() && File.Exists(WireGuardPath)
        ? RunAsync($"/uninstalltunnelservice {TunnelName}", tolerateFailure: true)
        : Task.CompletedTask;

    private async Task RunAsync(string arguments, bool tolerateFailure = false)
    {
        using var process = Process.Start(new ProcessStartInfo(WireGuardPath, arguments)
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
