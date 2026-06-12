using System.Diagnostics;
using System.Reflection;
using System.Text.Json;

namespace ToolEditDeleteCmt;

public sealed class GitHubUpdateChecker
{
    private const string Owner = "dinhquangtuy";
    private const string Repo = "FlowMeta_Release";
    private static readonly Uri LatestReleaseUri = new($"https://api.github.com/repos/{Owner}/{Repo}/releases/latest");

    public string CurrentVersionText => GetCurrentVersion().ToString();
    public string RepositoryUrl => $"https://github.com/{Owner}/{Repo}";

    public async Task<UpdateCheckResult> CheckAsync(CancellationToken cancellationToken = default)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(20) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("FlowMeta-Updater/1.0");
        client.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github+json");

        using var response = await client.GetAsync(LatestReleaseUri, cancellationToken);
        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return UpdateCheckResult.NoRelease("Chưa có GitHub Release nào cho repo này.");
        }

        var json = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            return UpdateCheckResult.Error($"GitHub API lỗi {(int)response.StatusCode}: {ExtractGitHubMessage(json)}");
        }

        var release = JsonSerializer.Deserialize<GitHubReleaseResponse>(json, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        });
        if (release is null || string.IsNullOrWhiteSpace(release.TagName))
        {
            return UpdateCheckResult.Error("Không đọc được thông tin release mới nhất.");
        }

        var currentVersion = GetCurrentVersion();
        var latestVersion = ParseVersion(release.TagName);
        if (latestVersion <= currentVersion)
        {
            return UpdateCheckResult.UpToDate(
                release.TagName,
                release.HtmlUrl,
                $"Đang dùng bản mới nhất: {currentVersion}.");
        }

        var asset = release.Assets
            .FirstOrDefault(item => item.Name.Equals("FlowMeta.exe", StringComparison.OrdinalIgnoreCase)) ??
                    release.Assets.FirstOrDefault(item => item.Name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase));

        return UpdateCheckResult.UpdateAvailable(
            release.TagName,
            release.Name,
            release.HtmlUrl,
            asset?.BrowserDownloadUrl,
            $"Có bản mới {release.TagName}. Bản hiện tại: {currentVersion}.");
    }

    public static void OpenUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            return;
        }

        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
    }

    private static Version GetCurrentVersion()
    {
        var versionText = Assembly.GetExecutingAssembly()
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?
            .InformationalVersion;
        if (string.IsNullOrWhiteSpace(versionText))
        {
            versionText = Assembly.GetExecutingAssembly().GetName().Version?.ToString();
        }

        return ParseVersion(versionText ?? "0.0.0");
    }

    private static Version ParseVersion(string value)
    {
        var clean = value.Trim();
        if (clean.StartsWith('v') || clean.StartsWith('V'))
        {
            clean = clean[1..];
        }

        var plusIndex = clean.IndexOf('+', StringComparison.Ordinal);
        if (plusIndex >= 0)
        {
            clean = clean[..plusIndex];
        }

        var dashIndex = clean.IndexOf('-', StringComparison.Ordinal);
        if (dashIndex >= 0)
        {
            clean = clean[..dashIndex];
        }

        return Version.TryParse(clean, out var version) ? version : new Version(0, 0, 0);
    }

    private static string ExtractGitHubMessage(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            return document.RootElement.TryGetProperty("message", out var message)
                ? message.GetString() ?? json
                : json;
        }
        catch
        {
            return json;
        }
    }

    private sealed class GitHubReleaseResponse
    {
        public string TagName { get; set; } = "";
        public string Name { get; set; } = "";
        public string HtmlUrl { get; set; } = "";
        public List<GitHubReleaseAsset> Assets { get; set; } = [];
    }

    private sealed class GitHubReleaseAsset
    {
        public string Name { get; set; } = "";
        public string BrowserDownloadUrl { get; set; } = "";
    }
}

public sealed record UpdateCheckResult(
    bool Success,
    bool HasUpdate,
    string LatestVersion,
    string ReleaseName,
    string ReleaseUrl,
    string? DownloadUrl,
    string Message)
{
    public static UpdateCheckResult NoRelease(string message)
    {
        return new UpdateCheckResult(true, false, "", "", "", null, message);
    }

    public static UpdateCheckResult UpToDate(string latestVersion, string releaseUrl, string message)
    {
        return new UpdateCheckResult(true, false, latestVersion, "", releaseUrl, null, message);
    }

    public static UpdateCheckResult UpdateAvailable(
        string latestVersion,
        string releaseName,
        string releaseUrl,
        string? downloadUrl,
        string message)
    {
        return new UpdateCheckResult(true, true, latestVersion, releaseName, releaseUrl, downloadUrl, message);
    }

    public static UpdateCheckResult Error(string message)
    {
        return new UpdateCheckResult(false, false, "", "", "", null, message);
    }
}
