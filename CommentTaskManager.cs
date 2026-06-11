using System.Collections.Concurrent;

namespace ToolEditDeleteCmt;

public sealed class CommentTaskManager
{
    private readonly ProfileManager _profileManager;
    private readonly ProxyManager _proxyManager;
    private readonly ICommentService _commentService;
    private readonly GraphCommentAuthorResolver _graphAuthorResolver;
    private readonly Random _random = new();
    private readonly object _statsSync = new();
    private readonly ConcurrentDictionary<string, TokenIssueInfo> _blockedProfiles = new(StringComparer.OrdinalIgnoreCase);
    private CancellationTokenSource? _cts;
    private int _logIndex;

    public CommentTaskManager(
        ProfileManager profileManager,
        ProxyManager proxyManager,
        ICommentService commentService,
        GraphCommentAuthorResolver graphAuthorResolver)
    {
        _profileManager = profileManager;
        _proxyManager = proxyManager;
        _commentService = commentService;
        _graphAuthorResolver = graphAuthorResolver;
    }

    public event Action<TaskLogEntry>? LogAdded;
    public event Action<TaskStats>? StatsChanged;
    public event Action<string, string, string>? ProfileStatusChanged;

    public TaskStats Stats { get; private set; } = new();

    public bool IsRunning => _cts is not null;

    public Task StartAsync(
        IReadOnlyList<CommentTaskInput> tasks,
        CommentActionKind action,
        int maxThreads,
        DelaySettings delaySettings,
        string newTextInput,
        string? imageInput)
    {
        Stop();
        _cts = new CancellationTokenSource();
        _blockedProfiles.Clear();
        Stats = new TaskStats { Total = tasks.Count };
        StatsChanged?.Invoke(Stats);

        var images = LoadImages(imageInput);
        var textVariants = LoadTextVariants(newTextInput);

        return Task.Run(async () =>
        {
            try
            {
                await RunGroupedByUidAsync(tasks, action, maxThreads, delaySettings, textVariants, images, _cts.Token);
            }
            catch (OperationCanceledException)
            {
            }
            catch (IOException ex) when (ex.Message.Contains("aborted", StringComparison.OrdinalIgnoreCase))
            {
            }
            finally
            {
                _cts?.Dispose();
                _cts = null;
            }
        }, _cts.Token);
    }

    public void Stop()
    {
        _cts?.Cancel();
    }

    private async Task RunGroupedByUidAsync(
        IReadOnlyList<CommentTaskInput> tasks,
        CommentActionKind action,
        int maxUidThreads,
        DelaySettings delaySettings,
        IReadOnlyList<string> textVariants,
        IReadOnlyList<string> images,
        CancellationToken cancellationToken)
    {
        var resolvedTasks = await ResolveTasksAsync(tasks, action, cancellationToken);
        if (resolvedTasks.Count == 0 || cancellationToken.IsCancellationRequested)
        {
            return;
        }

        var groups = resolvedTasks
            .GroupBy(task => task.Uid)
            .Select(group => new UidTaskGroup(group.Key, group.ToList()))
            .ToList();

        var batchSize = Math.Max(1, maxUidThreads);
        var roundsCompleted = 0;
        var batches = BuildUidRoundBatches(groups, batchSize);

        for (var i = 0; i < batches.Count && !cancellationToken.IsCancellationRequested; i++)
        {
            var batch = batches[i];
            var activeBatch = new List<ResolvedCommentTask>();
            var skipped = 0;
            foreach (var task in batch)
            {
                if (_blockedProfiles.ContainsKey(task.Uid))
                {
                    skipped++;
                    continue;
                }

                activeBatch.Add(task);
            }

            if (skipped > 0)
            {
                Increment(failed: skipped, processed: skipped);
            }

            if (activeBatch.Count == 0)
            {
                continue;
            }

            PreAddTaskLogs(activeBatch, action);
            await Task.WhenAll(activeBatch.Select(task => ProcessSingleTaskAsync(task, action, textVariants, images, cancellationToken)));

            roundsCompleted++;
            if (ShouldDelay(delaySettings, roundsCompleted, i < batches.Count - 1))
            {
                var delaySeconds = PickDelaySeconds(delaySettings);
                await Task.Delay(TimeSpan.FromSeconds(delaySeconds), cancellationToken);
            }
        }
    }

    private async Task<List<ResolvedCommentTask>> ResolveTasksAsync(
        IReadOnlyList<CommentTaskInput> tasks,
        CommentActionKind action,
        CancellationToken cancellationToken)
    {
        var resolved = new List<ResolvedCommentTask>();
        var checkerProfile = _profileManager.Profiles.FirstOrDefault();
        foreach (var task in tasks)
        {
            if (cancellationToken.IsCancellationRequested)
            {
                break;
            }

            var uid = task.ManualUid;
            if (string.IsNullOrWhiteSpace(uid))
            {
                if (checkerProfile is null)
                {
                    AddLog("", task.CommentLink, action, "Direct", "That bai", "Chưa có token để kiểm tra UID bằng Graph.", BuildLogKey(action, task.CommentLink));
                    Increment(failed: 1, processed: 1);
                    continue;
                }

                var graphResult = await _graphAuthorResolver.ResolveAuthorUidAsync(task.CommentLink, checkerProfile, proxy: null, cancellationToken);
                uid = graphResult.Uid;

                if (string.IsNullOrWhiteSpace(uid))
                {
                    AddLog(checkerProfile.Uid, task.CommentLink, action, "Direct", "That bai", $"Không lấy được UID bằng Graph. {graphResult.Message}", BuildLogKey(action, task.CommentLink));
                    Increment(failed: 1, processed: 1);
                    continue;
                }

            }

            resolved.Add(new ResolvedCommentTask(uid.Trim(), task.CommentLink));
        }

        return resolved;
    }

    private static List<List<ResolvedCommentTask>> BuildUidRoundBatches(
        IReadOnlyList<UidTaskGroup> groups,
        int batchSize)
    {
        var queues = groups
            .Select(group => new Queue<ResolvedCommentTask>(group.Tasks))
            .Where(queue => queue.Count > 0)
            .ToList();
        var batches = new List<List<ResolvedCommentTask>>();
        var cursor = 0;

        while (queues.Count > 0)
        {
            var batch = new List<ResolvedCommentTask>();
            var takeCount = Math.Min(batchSize, queues.Count);

            for (var i = 0; i < takeCount && queues.Count > 0; i++)
            {
                if (cursor >= queues.Count)
                {
                    cursor = 0;
                }

                var queue = queues[cursor];
                batch.Add(queue.Dequeue());

                if (queue.Count == 0)
                {
                    queues.RemoveAt(cursor);
                    if (cursor >= queues.Count)
                    {
                        cursor = 0;
                    }
                }
                else
                {
                    cursor = (cursor + 1) % queues.Count;
                }
            }

            if (batch.Count > 0)
            {
                batches.Add(batch);
            }
        }

        return batches;
    }

    private void PreAddTaskLogs(IReadOnlyList<ResolvedCommentTask> tasks, CommentActionKind action)
    {
        foreach (var task in tasks)
        {
            AddLog(task.Uid, task.CommentLink, action, "", "Cho chay", "", BuildLogKey(action, task.CommentLink));
        }
    }

    private async Task ProcessSingleTaskAsync(
        ResolvedCommentTask task,
        CommentActionKind action,
        IReadOnlyList<string> textVariants,
        IReadOnlyList<string> images,
        CancellationToken cancellationToken)
    {
        var profile = _profileManager.FindByUid(task.Uid);
        var logKey = BuildLogKey(action, task.CommentLink);
        if (_blockedProfiles.TryGetValue(task.Uid, out var blockedIssue))
        {
            AddLog(task.Uid, task.CommentLink, action, "", "Dung profile", $"Profile đã dừng do {blockedIssue.Status}.", logKey);
            Increment(failed: 1, processed: 1);
            return;
        }

        if (profile is null)
        {
            AddLog(task.Uid, task.CommentLink, action, "", "That bai", "UID comment không có trong tab Hồ sơ.", logKey);
            Increment(failed: 1, processed: 1);
            return;
        }

        ProxyLease? lease = null;
        var waitingProxyAdded = false;
        try
        {
            if (_proxyManager.IsStarted)
            {
                lease = _proxyManager.TryAcquireNow();
                if (lease is null)
                {
                    AddLog(profile.Uid, task.CommentLink, action, "", "Dang cho proxy", "Proxy đang lấy IP mới hoặc chưa sẵn sàng.", logKey);
                    Increment(waitingProxy: 1);
                    waitingProxyAdded = true;
                    lease = await _proxyManager.AcquireAsync(cancellationToken);
                    Increment(waitingProxy: -1);
                    waitingProxyAdded = false;
                }
            }
            else
            {
                lease = _proxyManager.TryAcquireNow();
            }

            var proxy = lease?.Endpoint;
            var proxyDisplay = proxy?.Display ?? "Direct";
            var imagePath = PickImage(images);
            var request = new CommentRequest
            {
                Profile = profile,
                CommentLink = task.CommentLink,
                Action = action,
                NewText = PickText(textVariants),
                ImagePath = imagePath,
                Proxy = proxy
            };

            AddLog(profile.Uid, task.CommentLink, action, proxyDisplay, "Dang chay", string.IsNullOrWhiteSpace(imagePath) ? "" : $"Ảnh: {Path.GetFileName(imagePath)}", logKey);
            var result = await _commentService.ExecuteAsync(request, cancellationToken);
            lease?.MarkUsed();

            profile.TaskCount++;
            profile.LastError = result.Success ? "" : result.Message;
            if (result.TokenIssue is not null)
            {
                BlockProfile(profile, result.TokenIssue, result.Message);
            }

            var status = result.Success ? "Thanh cong" : result.TokenIssue?.Status ?? "That bai";
            AddLog(profile.Uid, result.Success && !string.IsNullOrWhiteSpace(result.OutputLink) ? result.OutputLink : task.CommentLink, action, proxyDisplay, status, result.Message, logKey);
            Increment(result.Success ? 1 : 0, result.Success ? 0 : 1, processed: 1);
        }
        catch (OperationCanceledException)
        {
            if (waitingProxyAdded)
            {
                Increment(waitingProxy: -1);
            }

            lease?.Dispose();
            AddLog(profile.Uid, task.CommentLink, action, lease?.Endpoint.Display ?? "", "Dung", "Đã nhận lệnh dừng.", logKey);
            Increment(processed: 1);
        }
        catch (Exception ex)
        {
            if (waitingProxyAdded)
            {
                Increment(waitingProxy: -1);
            }

            lease?.MarkUsed();
            profile.LastError = ex.Message;
            AddLog(profile.Uid, task.CommentLink, action, lease?.Endpoint.Display ?? "", "That bai", ex.Message, logKey);
            Increment(failed: 1, processed: 1);
        }
    }

    private void BlockProfile(ProfileAccount profile, TokenIssueInfo issue, string message)
    {
        _blockedProfiles.TryAdd(profile.Uid, issue);
        profile.TokenStatus = issue.Status;
        profile.LastError = message;
        ProfileStatusChanged?.Invoke(profile.Uid, profile.TokenStatus, profile.LastError);
    }

    private static bool ShouldDelay(DelaySettings delaySettings, int roundsCompleted, bool hasMoreGroups)
    {
        return hasMoreGroups &&
               delaySettings.Enabled &&
               delaySettings.EveryRounds > 0 &&
               roundsCompleted % delaySettings.EveryRounds == 0;
    }

    private int PickDelaySeconds(DelaySettings delaySettings)
    {
        var min = Math.Max(0, Math.Min(delaySettings.MinSeconds, delaySettings.MaxSeconds));
        var max = Math.Max(0, Math.Max(delaySettings.MinSeconds, delaySettings.MaxSeconds));
        if (max <= min)
        {
            return min;
        }

        lock (_random)
        {
            return _random.Next(min, max + 1);
        }
    }

    public static IReadOnlyList<string> LoadImages(string? imageInput)
    {
        if (string.IsNullOrWhiteSpace(imageInput))
        {
            return [];
        }

        var extensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            ".jpg", ".jpeg", ".jfif", ".pjpeg", ".pjp",
            ".png", ".gif", ".webp", ".bmp", ".dib",
            ".tif", ".tiff", ".heic", ".heif", ".avif",
            ".ico", ".svg"
        };

        var images = new List<string>();
        foreach (var rawLine in imageInput.Replace("\r\n", "\n").Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var path = rawLine.Trim().Trim('"');
            if (File.Exists(path))
            {
                if (IsImagePath(path, extensions))
                {
                    images.Add(Path.GetFullPath(path));
                }

                continue;
            }

            if (!Directory.Exists(path))
            {
                continue;
            }

            try
            {
                images.AddRange(Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories)
                    .Where(file => IsImagePath(file, extensions))
                    .Select(Path.GetFullPath));
            }
            catch
            {
                images.AddRange(Directory.EnumerateFiles(path, "*", SearchOption.TopDirectoryOnly)
                    .Where(file => IsImagePath(file, extensions))
                    .Select(Path.GetFullPath));
            }
        }

        return images
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static IReadOnlyList<string> LoadTextVariants(string textInput)
    {
        if (string.IsNullOrWhiteSpace(textInput))
        {
            return [];
        }

        var normalized = textInput.Replace("\r\n", "\n").Trim();
        var blocks = normalized
            .Split(["\n\n"], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(block => !string.IsNullOrWhiteSpace(block))
            .ToList();

        return blocks.Count > 0 ? blocks : [normalized];
    }

    private static bool IsImagePath(string path, HashSet<string> extensions)
    {
        var extension = Path.GetExtension(path).Trim();
        return !string.IsNullOrWhiteSpace(extension) && extensions.Contains(extension);
    }

    private string? PickImage(IReadOnlyList<string> images)
    {
        if (images.Count == 0)
        {
            return null;
        }

        lock (_random)
        {
            return images[_random.Next(images.Count)];
        }
    }

    private string PickText(IReadOnlyList<string> textVariants)
    {
        if (textVariants.Count == 0)
        {
            return "";
        }

        lock (_random)
        {
            return textVariants[_random.Next(textVariants.Count)];
        }
    }

    private static string BuildLogKey(CommentActionKind action, string link)
    {
        return $"{action}|{link.Trim()}";
    }

    private void AddLog(string uid, string link, CommentActionKind action, string proxy, string status, string error, string key)
    {
        LogAdded?.Invoke(new TaskLogEntry
        {
            Key = key,
            Index = Interlocked.Increment(ref _logIndex),
            Uid = uid,
            CommentLink = link,
            Action = action switch
            {
                CommentActionKind.Edit => "Edit",
                CommentActionKind.Delete => "Delete",
                CommentActionKind.NewComment => "Comment moi",
                _ => action.ToString()
            },
            Proxy = proxy,
            Status = status,
            Error = error
        });
    }

    private void Increment(int success = 0, int failed = 0, int processed = 0, int waitingProxy = 0)
    {
        lock (_statsSync)
        {
            Stats = Stats with
            {
                Success = Math.Max(0, Stats.Success + success),
                Failed = Math.Max(0, Stats.Failed + failed),
                Processed = Math.Max(0, Stats.Processed + processed),
                WaitingProxy = Math.Max(0, Stats.WaitingProxy + waitingProxy)
            };
        }

        StatsChanged?.Invoke(Stats);
    }
}

public sealed record CommentTaskInput(string ManualUid, string CommentLink);

public sealed record ResolvedCommentTask(string Uid, string CommentLink);

public sealed record UidTaskGroup(string Uid, IReadOnlyList<ResolvedCommentTask> Tasks);

public sealed record TaskStats
{
    public int Total { get; init; }
    public int Processed { get; init; }
    public int Success { get; init; }
    public int Failed { get; init; }
    public int WaitingProxy { get; init; }
}
