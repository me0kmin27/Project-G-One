using System.Diagnostics;
using System.IO;

namespace GOne.Client;

internal sealed class WindowsVpnManager
{
    private const string TunnelName = "GOne";
    private const string InstallerResource = "GOne.Client.Resources.wireguard-installer.exe";
    private static readonly string WireGuardPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "WireGuard", "wireguard.exe");

    public async Task ConnectAsync(string configuration)
    {
        if (!OperatingSystem.IsWindows())
            throw new PlatformNotSupportedException("VPN 연결은 Windows에서만 지원됩니다.");
        await EnsureRuntimeAsync();

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

    private static async Task EnsureRuntimeAsync()
    {
        if (File.Exists(WireGuardPath)) return;

        var installerPath = Path.Combine(Path.GetTempPath(), $"GOne-WireGuard-{Guid.NewGuid():N}.exe");
        await using (var resource = typeof(WindowsVpnManager).Assembly.GetManifestResourceStream(InstallerResource)
            ?? throw new InvalidOperationException("내장 VPN 런타임을 찾을 수 없습니다."))
        await using (var installer = File.Create(installerPath))
            await resource.CopyToAsync(installer);

        try
        {
            using var process = Process.Start(new ProcessStartInfo(installerPath, "/install")
            {
                UseShellExecute = true,
                Verb = "runas",
            }) ?? throw new InvalidOperationException("내장 VPN 런타임 설치를 시작할 수 없습니다.");
            await process.WaitForExitAsync();
            if (process.ExitCode != 0 || !File.Exists(WireGuardPath))
                throw new InvalidOperationException($"내장 VPN 런타임 준비에 실패했습니다 ({process.ExitCode}).");
        }
        finally
        {
            File.Delete(installerPath);
        }
    }
}
