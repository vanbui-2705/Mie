using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ToolEditDeleteCmt;

public sealed class GitHubUpdateChecker
{
    private const string Owner = "dinhquangtuy";
    private const string Repo = "FlowMeta_Release";
    private static readonly Uri ReleasesUri = new($"https://api.github.com/repos/{Owner}/{Repo}/releases?per_page=20");

    public Version CurrentVersion => GetCurrentVersion();
    public string CurrentVersionText => CurrentVersion.ToString();

    public async Task<UpdateHistoryResult> GetReleaseHistoryAsync(CancellationToken cancellationToken = default)
    {
        using var client = CreateClient();
        using var response = await client.GetAsync(ReleasesUri, cancellationToken);
        var json = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            return UpdateHistoryResult.Error($"GitHub API lỗi {(int)response.StatusCode}: {ExtractGitHubMessage(json)}");
        }

        var releases = JsonSerializer.Deserialize<List<GitHubReleaseResponse>>(json) ?? [];
        if (releases.Count == 0)
        {
            return UpdateHistoryResult.Success([], null, "Chưa có bản phát hành nào trên GitHub.");
        }

        var current = CurrentVersion;
        var items = releases
            .Where(release => !string.IsNullOrWhiteSpace(release.TagName))
            .Select(release =>
            {
                var asset = release.Assets
                    .FirstOrDefault(item => item.Name.Equals("FlowMeta.exe", StringComparison.OrdinalIgnoreCase)) ??
                            release.Assets.FirstOrDefault(item => item.Name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase));
                var version = ParseVersion(release.TagName);
                return new UpdateReleaseInfo(
                    release.TagName,
                    version,
                    release.Name,
                    release.Body,
                    release.HtmlUrl,
                    asset?.BrowserDownloadUrl ?? "",
                    release.PublishedAt,
                    version > current);
            })
            .OrderByDescending(item => item.Version)
            .ToList();

        var latest = items.FirstOrDefault(item => item.IsNewerThanCurrent);
        var message = latest is null
            ? $"Bạn đang dùng bản mới nhất: {current}."
            : $"Có bản mới {latest.TagName}. Bản hiện tại: {current}.";
        return UpdateHistoryResult.Success(items, latest, message);
    }

    public async Task<string> DownloadUpdateAsync(
        UpdateReleaseInfo release,
        IProgress<int>? progress = null,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(release.DownloadUrl))
        {
            throw new InvalidOperationException("Release này chưa có file FlowMeta.exe.");
        }

        var tempDir = Path.Combine(Path.GetTempPath(), "FlowMetaUpdate");
        Directory.CreateDirectory(tempDir);
        var outputPath = Path.Combine(tempDir, "FlowMeta.exe");

        using var client = CreateClient();
        using var response = await client.GetAsync(release.DownloadUrl, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        response.EnsureSuccessStatusCode();

        var total = response.Content.Headers.ContentLength;
        await using var input = await response.Content.ReadAsStreamAsync(cancellationToken);
        await using var output = File.Create(outputPath);

        var buffer = new byte[1024 * 128];
        long downloaded = 0;
        while (true)
        {
            var read = await input.ReadAsync(buffer, cancellationToken);
            if (read <= 0)
            {
                break;
            }

            await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
            downloaded += read;
            if (total is > 0)
            {
                progress?.Report((int)Math.Clamp(downloaded * 100 / total.Value, 0, 100));
            }
        }

        progress?.Report(100);
        return outputPath;
    }

    public static void OpenUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            return;
        }

        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
    }

    private static HttpClient CreateClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("FlowMeta-Updater/1.0");
        client.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github+json");
        return client;
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
        [JsonPropertyName("tag_name")]
        public string TagName { get; set; } = "";

        [JsonPropertyName("name")]
        public string Name { get; set; } = "";

        [JsonPropertyName("body")]
        public string Body { get; set; } = "";

        [JsonPropertyName("html_url")]
        public string HtmlUrl { get; set; } = "";

        [JsonPropertyName("published_at")]
        public DateTimeOffset PublishedAt { get; set; }

        [JsonPropertyName("assets")]
        public List<GitHubReleaseAsset> Assets { get; set; } = [];
    }

    private sealed class GitHubReleaseAsset
    {
        [JsonPropertyName("name")]
        public string Name { get; set; } = "";

        [JsonPropertyName("browser_download_url")]
        public string BrowserDownloadUrl { get; set; } = "";
    }
}

public sealed record UpdateReleaseInfo(
    string TagName,
    Version Version,
    string Name,
    string Body,
    string ReleaseUrl,
    string DownloadUrl,
    DateTimeOffset PublishedAt,
    bool IsNewerThanCurrent);

public sealed record UpdateHistoryResult(
    bool IsSuccess,
    List<UpdateReleaseInfo> Releases,
    UpdateReleaseInfo? LatestUpdate,
    string Message)
{
    public static UpdateHistoryResult Success(
        List<UpdateReleaseInfo> releases,
        UpdateReleaseInfo? latestUpdate,
        string message)
    {
        return new UpdateHistoryResult(true, releases, latestUpdate, message);
    }

    public static UpdateHistoryResult Error(string message)
    {
        return new UpdateHistoryResult(false, [], null, message);
    }
}
