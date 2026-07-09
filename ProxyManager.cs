using System.Text.RegularExpressions;

namespace ToolEditDeleteCmt;

public sealed class ProxyManager
{
    private const int GetNewTimeoutSeconds = 15;
    public static readonly TimeSpan IpLifetime = TimeSpan.FromMinutes(30);

    private readonly object _sync = new();
    private readonly KiotProxyClient _client = new();
    private readonly List<ProxyKeyState> _states = [];
    private readonly Dictionary<string, int> _getNewVersions = new(StringComparer.OrdinalIgnoreCase);
    private CancellationTokenSource? _cts;
    private Task? _monitorTask;
    private AppSettings _settings = new();
    private int _nextProxyIndex;

    public event Action? StateChanged;

    public bool IsStarted => _cts is not null;

    public IReadOnlyList<ProxyKeyState> Snapshot()
    {
        lock (_sync)
        {
            return _states
                .Select(s => new ProxyKeyState
                {
                    Index = s.Index,
                    ApiKey = s.ApiKey,
                    CurrentProxy = s.CurrentProxy,
                    RemainingUses = s.RemainingUses,
                    ReservedUses = s.ReservedUses,
                    Status = s.Status,
                    LastGetIpAt = s.LastGetIpAt,
                    IpExpiresAt = s.IpExpiresAt,
                    LastCheckedAt = s.LastCheckedAt,
                    NextGetNewAt = s.NextGetNewAt,
                    LastError = s.LastError,
                    Endpoint = s.Endpoint
                })
                .ToList();
        }
    }

    public void Configure(AppSettings settings)
    {
        _settings = settings;
        var keys = settings.ProxyApiKeysText
            .Replace("\r\n", "\n")
            .Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Distinct()
            .ToList();

        lock (_sync)
        {
            _states.Clear();
            _getNewVersions.Clear();
            _nextProxyIndex = 0;
            for (var i = 0; i < keys.Count; i++)
            {
                _states.Add(new ProxyKeyState
                {
                    Index = i + 1,
                    ApiKey = keys[i],
                    Status = ""
                });
            }
        }

        StateChanged?.Invoke();
    }

    public void UpdateSettings(AppSettings settings)
    {
        _settings = settings;
    }

    public void Start()
    {
        CancelRunning();
        lock (_sync)
        {
            if (_states.Count == 0)
            {
                _nextProxyIndex = 0;
                _getNewVersions.Clear();
                StateChanged?.Invoke();
                return;
            }
        }

        _cts = new CancellationTokenSource();
        lock (_sync)
        {
            _nextProxyIndex = 0;
            _getNewVersions.Clear();
            foreach (var state in _states)
            {
                state.Status = "Starting";
                state.LastError = "";
            }
        }

        _monitorTask = Task.Run(() => MonitorAsync(_cts.Token));
        StateChanged?.Invoke();
    }

    public void Stop()
    {
        CancelRunning();

        lock (_sync)
        {
            _nextProxyIndex = 0;
            _states.Clear();
        }

        StateChanged?.Invoke();
    }

    private void CancelRunning()
    {
        _cts?.Cancel();
        _cts = null;
    }

    public async Task<ProxyLease> AcquireAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            var lease = TryAcquireNow();
            if (lease is not null)
            {
                return lease;
            }

            await Task.Delay(1000, cancellationToken);
        }

        throw new OperationCanceledException(cancellationToken);
    }

    public async Task<ProxyLease?> AcquireForTaskAsync(CancellationToken cancellationToken)
    {
        return IsStarted
            ? await AcquireAsync(cancellationToken)
            : TryAcquireNow();
    }

    public ProxyLease? TryAcquireNow()
    {
        lock (_sync)
        {
            if (_states.Count == 0)
            {
                return null;
            }

            for (var offset = 0; offset < _states.Count; offset++)
            {
                var index = (_nextProxyIndex + offset) % _states.Count;
                var candidate = _states[index];
                if (candidate.Endpoint is null ||
                    candidate.RemainingUses <= candidate.ReservedUses ||
                    IsIpExpired(candidate) ||
                    !IsReadyStatus(candidate.Status))
                {
                    continue;
                }

                candidate.ReservedUses++;
                _nextProxyIndex = (index + 1) % _states.Count;
                StateChanged?.Invoke();
                return new ProxyLease(this, candidate, candidate.Endpoint);
            }
        }

        return null;
    }

    public void CompleteLease(ProxyKeyState state, bool consumed)
    {
        var needsGetNew = false;
        lock (_sync)
        {
            var current = _states.FirstOrDefault(s => s.ApiKey == state.ApiKey);
            if (current is null)
            {
                return;
            }

            current.ReservedUses = Math.Max(0, current.ReservedUses - 1);
            if (consumed)
            {
                current.RemainingUses = Math.Max(0, current.RemainingUses - 1);
            }

            needsGetNew = current.RemainingUses <= 0 && _cts is not null;
            if (needsGetNew)
            {
                current.Status = "GettingNew";
                current.LastError = "";
                current.NextGetNewAt = null;
            }
        }

        StateChanged?.Invoke();
        if (needsGetNew && _cts is not null)
        {
            _ = GetNewProxyForKeyAsync(state.ApiKey, _cts.Token);
        }
    }

    private async Task MonitorAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            await CheckCurrentProxiesAsync(cancellationToken);

            List<string> keys;
            var now = DateTime.Now;
            lock (_sync)
            {
                keys = _states
                    .Where(s => ShouldRequestNewProxy(s, now))
                    .Select(s => s.ApiKey)
                    .ToList();
            }

            await Task.WhenAll(keys.Select(key => GetNewProxyForKeyAsync(key, cancellationToken)));

            try
            {
                var checkIntervalSeconds = Math.Clamp(_settings.ProxyCheckIntervalSeconds <= 0 ? 5 : _settings.ProxyCheckIntervalSeconds, 1, 3600);
                await Task.Delay(TimeSpan.FromSeconds(checkIntervalSeconds), cancellationToken);
            }
            catch (OperationCanceledException)
            {
                break;
            }
        }
    }

    private async Task CheckCurrentProxiesAsync(CancellationToken cancellationToken)
    {
        List<string> keys;
        lock (_sync)
        {
            keys = _states
                .Where(s =>
                    IsReadyStatus(s.Status) &&
                    s.Endpoint is not null &&
                    s.RemainingUses > 0)
                .Select(s => s.ApiKey)
                .ToList();
        }

        await Task.WhenAll(keys.Select(key => CheckCurrentProxyForKeyAsync(key, cancellationToken)));
    }

    private async Task CheckCurrentProxyForKeyAsync(string apiKey, CancellationToken cancellationToken)
    {
        try
        {
            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeoutCts.CancelAfter(TimeSpan.FromSeconds(GetNewTimeoutSeconds));

            var endpoint = await _client.GetCurrentProxyAsync(
                apiKey,
                _settings.KiotAuthToken,
                _settings.GetCurrentProxyUrlTemplate,
                timeoutCts.Token);

            lock (_sync)
            {
                var state = _states.FirstOrDefault(s => s.ApiKey == apiKey);
                if (state is null || state.Status == "GettingNew")
                {
                    return;
                }

                state.Endpoint = endpoint;
                state.CurrentProxy = endpoint.Display;
                state.IpExpiresAt = endpoint.ExpiresAt ?? state.IpExpiresAt;
                state.LastCheckedAt = DateTime.Now;
                state.Status = "Ready";
                state.LastError = endpoint.ApiMessage;
            }
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            SetCheckError(apiKey, $"Quá {GetNewTimeoutSeconds}s chưa kiểm tra được proxy.");
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception ex)
        {
            SetCheckError(apiKey, ex.Message);
        }
        finally
        {
            StateChanged?.Invoke();
        }
    }

    private async Task GetNewProxyForKeyAsync(string apiKey, CancellationToken cancellationToken)
    {
        var getNewVersion = BeginGetNew(apiKey);
        if (getNewVersion == 0)
        {
            return;
        }

        try
        {
            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeoutCts.CancelAfter(TimeSpan.FromSeconds(GetNewTimeoutSeconds));

            var endpoint = await _client.GetNewProxyAsync(
                apiKey,
                _settings.KiotAuthToken,
                _settings.GetNewProxyUrlTemplate,
                timeoutCts.Token);

            lock (_sync)
            {
                var state = _states.FirstOrDefault(s => s.ApiKey == apiKey);
                if (state is null || !IsCurrentGetNewVersion(apiKey, getNewVersion))
                {
                    return;
                }

                state.Endpoint = endpoint;
                state.CurrentProxy = endpoint.Display;
                state.RemainingUses = Math.Max(1, _settings.UsesPerProxy);
                state.ReservedUses = 0;
                state.Status = "Ready";
                state.LastGetIpAt = DateTime.Now;
                state.IpExpiresAt = endpoint.ExpiresAt ?? DateTime.Now.Add(IpLifetime);
                state.LastError = endpoint.ApiMessage;
                state.NextGetNewAt = null;
            }
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            if (!IsCurrentGetNewVersion(apiKey, getNewVersion))
            {
                return;
            }

            SetWaitingStatus(apiKey, $"Quá {GetNewTimeoutSeconds}s chưa lấy được IP, gọi lấy IP mới lại.", TimeSpan.FromSeconds(1));
        }
        catch (OperationCanceledException)
        {
            return;
        }
        catch (Exception ex)
        {
            if (!IsCurrentGetNewVersion(apiKey, getNewVersion))
            {
                return;
            }

            SetWaitingStatus(apiKey, ex.Message, TryGetRetryDelay(ex.Message));
        }
        finally
        {
            StateChanged?.Invoke();
        }
    }

    private int BeginGetNew(string apiKey)
    {
        lock (_sync)
        {
            var state = _states.FirstOrDefault(s => s.ApiKey == apiKey);
            if (state is null)
            {
                return 0;
            }

            var getNewVersion = _getNewVersions.TryGetValue(apiKey, out var currentVersion)
                ? currentVersion + 1
                : 1;
            _getNewVersions[apiKey] = getNewVersion;
            state.Status = "GettingNew";
            state.LastError = "";
            state.NextGetNewAt = null;
            return getNewVersion;
        }
    }

    private bool IsCurrentGetNewVersion(string apiKey, int getNewVersion)
    {
        lock (_sync)
        {
            return _getNewVersions.TryGetValue(apiKey, out var currentVersion) &&
                   currentVersion == getNewVersion;
        }
    }

    private static bool IsIpExpired(ProxyKeyState state)
    {
        return state.Endpoint is not null &&
               state.IpExpiresAt is not null &&
               DateTime.Now >= state.IpExpiresAt.Value;
    }

    private static bool IsReadyStatus(string status)
    {
        return status.Equals("Ready", StringComparison.OrdinalIgnoreCase);
    }

    private static bool ShouldRequestNewProxy(ProxyKeyState state, DateTime now)
    {
        if (state.Status == "GettingNew")
        {
            return false;
        }

        if (state.NextGetNewAt is not null && now < state.NextGetNewAt.Value)
        {
            return false;
        }

        return state.Endpoint is null ||
               state.RemainingUses <= 0 ||
               IsIpExpired(state) ||
               state.Status is "Starting" or "Error" or "Waiting";
    }

    private void SetStatus(string apiKey, string status, string error)
    {
        lock (_sync)
        {
            var state = _states.FirstOrDefault(s => s.ApiKey == apiKey);
            if (state is null)
            {
                return;
            }

            state.Status = status;
            state.LastError = error;
        }

        StateChanged?.Invoke();
    }

    private void SetWaitingStatus(string apiKey, string error, TimeSpan? retryDelay)
    {
        lock (_sync)
        {
            var state = _states.FirstOrDefault(s => s.ApiKey == apiKey);
            if (state is null)
            {
                return;
            }

            state.Status = "Waiting";
            state.LastError = NormalizeRetryMessage(error, retryDelay);
            var delay = retryDelay ?? TimeSpan.FromSeconds(Random.Shared.Next(1, 6));
            state.NextGetNewAt = DateTime.Now.Add(delay);
            state.LastError = NormalizeRetryMessage(error, delay);
        }

        StateChanged?.Invoke();
    }

    private static TimeSpan? TryGetRetryDelay(string message)
    {
        var match = Regex.Match(
            message,
            @"(?:Gửi lại sau|Gui lai sau|retry after|try again in)\s*(\d+)\s*(?:giây|giay|s|sec|secs|second|seconds)?",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        return match.Success && int.TryParse(match.Groups[1].Value, out var seconds) && seconds > 0
            ? TimeSpan.FromSeconds(seconds)
            : null;
    }

    private static string NormalizeRetryMessage(string error, TimeSpan? retryDelay)
    {
        return retryDelay is null
            ? error
            : $"Gửi lại sau {Math.Max(1, (int)Math.Ceiling(retryDelay.Value.TotalSeconds))}s";
    }

    private void SetCheckError(string apiKey, string error)
    {
        lock (_sync)
        {
            var state = _states.FirstOrDefault(s => s.ApiKey == apiKey);
            if (state is null || state.Status == "GettingNew")
            {
                return;
            }

            state.LastCheckedAt = DateTime.Now;
            state.LastError = error;
        }

        StateChanged?.Invoke();
    }
}
