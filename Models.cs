using System.Net;

namespace ToolEditDeleteCmt;

public enum CommentActionKind
{
    Edit,
    Delete,
    NewComment
}

public sealed class ProfileAccount
{
    public int Index { get; set; }
    public string Uid { get; set; } = "";
    public string Token { get; set; } = "";
    public string TokenStatus { get; set; } = "Chua kiem tra";
    public int TaskCount { get; set; }
    public string LastError { get; set; } = "";

    public string MaskedToken => SecretMasker.Mask(Token);
}

public sealed class ProxyKeyState
{
    public int Index { get; set; }
    public string ApiKey { get; set; } = "";
    public string CurrentProxy { get; set; } = "";
    public int RemainingUses { get; set; }
    public int ReservedUses { get; set; }
    public string Status { get; set; } = "Stopped";
    public DateTime? LastGetIpAt { get; set; }
    public DateTime? IpExpiresAt { get; set; }
    public DateTime? LastCheckedAt { get; set; }
    public DateTime? NextGetNewAt { get; set; }
    public string LastError { get; set; } = "";
    public ProxyEndpoint? Endpoint { get; set; }

    public string MaskedApiKey => SecretMasker.Mask(ApiKey);
}

public sealed class ProxyEndpoint
{
    public string Host { get; set; } = "";
    public int HttpPort { get; set; }
    public string? Username { get; set; }
    public string? Password { get; set; }
    public string Display { get; set; } = "";
    public DateTime? ExpiresAt { get; set; }
    public string ApiStatus { get; set; } = "";
    public string ApiMessage { get; set; } = "";

    public WebProxy ToWebProxy()
    {
        var proxy = new WebProxy($"http://{Host}:{HttpPort}");
        if (!string.IsNullOrWhiteSpace(Username))
        {
            proxy.Credentials = new NetworkCredential(Username, Password ?? "");
        }

        return proxy;
    }
}

public sealed class ProxyLease : IDisposable
{
    private readonly ProxyManager _manager;
    private bool _completed;

    public ProxyLease(ProxyManager manager, ProxyKeyState state, ProxyEndpoint endpoint)
    {
        _manager = manager;
        State = state;
        Endpoint = endpoint;
    }

    public ProxyKeyState State { get; }
    public ProxyEndpoint Endpoint { get; }

    public void MarkUsed()
    {
        if (_completed)
        {
            return;
        }

        _completed = true;
        _manager.CompleteLease(State, consumed: true);
    }

    public void Dispose()
    {
        if (_completed)
        {
            return;
        }

        _completed = true;
        _manager.CompleteLease(State, consumed: false);
    }
}

public sealed class DirectLease : IDisposable
{
    public ProxyEndpoint? Endpoint => null;
    public string Display => "Direct";

    public void MarkUsed()
    {
    }

    public void Dispose()
    {
    }
}

public sealed class TaskLogEntry
{
    public string Key { get; set; } = "";
    public int Index { get; set; }
    public string Uid { get; set; } = "";
    public string CommentLink { get; set; } = "";
    public string Action { get; set; } = "";
    public string Proxy { get; set; } = "";
    public string Status { get; set; } = "";
    public string Error { get; set; } = "";
}

public sealed record DelaySettings(int MinSeconds, int MaxSeconds, int EveryRounds)
{
    public bool Enabled => EveryRounds > 0 && (MinSeconds > 0 || MaxSeconds > 0);
}

public sealed class AppSettings
{
    public string ProfileText { get; set; } = "";
    public Dictionary<string, SavedProfileState> ProfileStates { get; set; } = [];
    public string InteractionUidText { get; set; } = "";
    public string InteractionLinkText { get; set; } = "";
    public string InteractionPostIdText { get; set; } = "";
    public int InteractionActionIndex { get; set; }
    public string EditUidText { get; set; } = "";
    public string EditLinkText { get; set; } = "";
    public string DeleteUidText { get; set; } = "";
    public string DeleteLinkText { get; set; } = "";
    public string NewCommentUidText { get; set; } = "";
    public string NewCommentPostText { get; set; } = "";
    public int InteractionThreads { get; set; } = 5;
    public int InteractionDelayMinSeconds { get; set; }
    public int InteractionDelayMaxSeconds { get; set; }
    public int InteractionDelayEveryRounds { get; set; } = 1;
    public int InteractionPostsPerUid { get; set; } = 1;
    public string InteractionEditText { get; set; } = "";
    public string InteractionImageFolder { get; set; } = "";
    public string KiotAuthToken { get; set; } = "";
    public string ProxyApiKeysText { get; set; } = "";
    public string GetNewProxyUrlTemplate { get; set; } = "https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}";
    public string GetCurrentProxyUrlTemplate { get; set; } = "https://api.kiotproxy.com/api/v1/proxies/current?key={apiKey}";
    public int UsesPerProxy { get; set; } = 4;
    public int ProxyCheckIntervalSeconds { get; set; } = 5;
}

public sealed class SavedProfileState
{
    public string TokenStatus { get; set; } = "";
    public int TaskCount { get; set; }
    public string LastError { get; set; } = "";
}

public static class SecretMasker
{
    public static string Mask(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return "";
        }

        if (value.Length <= 8)
        {
            return new string('*', value.Length);
        }

        return $"{value[..4]}***{value[^4..]}";
    }
}
