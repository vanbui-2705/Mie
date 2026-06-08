namespace ToolEditDeleteCmt;

public sealed class ProxyManager
{
    private readonly object _sync = new();
    private readonly KiotProxyClient _client = new();
    private readonly List<ProxyKeyState> _states = [];
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
            _nextProxyIndex = 0;
            for (var i = 0; i < keys.Count; i++)
            {
                _states.Add(new ProxyKeyState
                {
                    Index = i + 1,
                    ApiKey = keys[i],
                    Status = "Stopped"
                });
            }
        }

        StateChanged?.Invoke();
    }

    public void Start()
    {
        Stop();
        _cts = new CancellationTokenSource();
        lock (_sync)
        {
            _nextProxyIndex = 0;
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
        _cts?.Cancel();
        _cts = null;

        lock (_sync)
        {
            _nextProxyIndex = 0;
            foreach (var state in _states)
            {
                state.Status = "Stopped";
                state.ReservedUses = 0;
            }
        }

        StateChanged?.Invoke();
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
                    !string.Equals(candidate.Status, "Ready", StringComparison.OrdinalIgnoreCase))
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
        var needsRefresh = false;
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

            needsRefresh = current.RemainingUses <= 0 && _cts is not null;
            if (needsRefresh)
            {
                current.Status = "Refreshing";
            }
        }

        StateChanged?.Invoke();
        if (needsRefresh && _cts is not null)
        {
            _ = RefreshOneAsync(state.ApiKey, _cts.Token);
        }
    }

    private async Task MonitorAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            List<string> keys;
            lock (_sync)
            {
                keys = _states
                    .Where(s =>
                        s.Status != "Refreshing" &&
                        (s.Endpoint is null ||
                         s.RemainingUses <= 0 ||
                         s.Status is "Starting" or "Error" or "Waiting"))
                    .Select(s => s.ApiKey)
                    .ToList();
            }

            foreach (var key in keys)
            {
                await RefreshOneAsync(key, cancellationToken);
            }

            try
            {
                await Task.Delay(TimeSpan.FromSeconds(5), cancellationToken);
            }
            catch (OperationCanceledException)
            {
                break;
            }
        }
    }

    private async Task RefreshOneAsync(string apiKey, CancellationToken cancellationToken)
    {
        SetStatus(apiKey, "Refreshing", "");
        try
        {
            var endpoint = await _client.GetNewProxyAsync(
                apiKey,
                _settings.KiotAuthToken,
                _settings.GetNewProxyUrlTemplate,
                cancellationToken);

            lock (_sync)
            {
                var state = _states.FirstOrDefault(s => s.ApiKey == apiKey);
                if (state is null)
                {
                    return;
                }

                state.Endpoint = endpoint;
                state.CurrentProxy = endpoint.Display;
                state.RemainingUses = Math.Max(1, _settings.UsesPerProxy);
                state.ReservedUses = 0;
                state.Status = "Ready";
                state.LastGetIpAt = DateTime.Now;
                state.LastError = "";
            }
        }
        catch (OperationCanceledException)
        {
            return;
        }
        catch (Exception ex)
        {
            SetStatus(apiKey, "Waiting", ex.Message);
        }
        finally
        {
            StateChanged?.Invoke();
        }
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
}
