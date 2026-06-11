namespace ToolEditDeleteCmt;

public sealed class ProfileManager
{
    private readonly List<ProfileAccount> _profiles = [];
    private int _nextProfile;

    public IReadOnlyList<ProfileAccount> Profiles => _profiles;

    public ParseResult LoadFromText(string text)
    {
        _profiles.Clear();
        _nextProfile = 0;
        return MergeFromText(text);
    }

    public ParseResult MergeFromText(string text)
    {
        var errors = new List<string>();
        var duplicateCount = 0;
        var addedCount = 0;
        var profilesByUid = _profiles.ToDictionary(profile => profile.Uid, StringComparer.OrdinalIgnoreCase);
        var lines = text.Replace("\r\n", "\n").Split('\n');
        foreach (var rawLine in lines)
        {
            var line = rawLine.Trim();
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            var parts = line.Split('|', 2);
            if (parts.Length != 2 || string.IsNullOrWhiteSpace(parts[0]) || string.IsNullOrWhiteSpace(parts[1]))
            {
                errors.Add($"Sai định dạng: {line}");
                continue;
            }

            var uid = parts[0].Trim();
            var token = parts[1].Trim();
            if (profilesByUid.TryGetValue(uid, out var existing))
            {
                existing.Token = token;
                existing.TokenStatus = "Da refresh token";
                existing.LastError = "";
                duplicateCount++;
                continue;
            }

            var profile = new ProfileAccount
            {
                Index = _profiles.Count + 1,
                Uid = uid,
                Token = token,
                TokenStatus = "Da nap"
            };
            _profiles.Add(profile);
            profilesByUid[uid] = profile;
            addedCount++;
        }

        Reindex();
        return new ParseResult(_profiles.Count, errors, duplicateCount, addedCount);
    }

    public void Clear()
    {
        _profiles.Clear();
        _nextProfile = 0;
    }

    public int RemoveByUids(IEnumerable<string> uids)
    {
        var uidSet = new HashSet<string>(
            uids
                .Where(uid => !string.IsNullOrWhiteSpace(uid))
                .Select(uid => uid.Trim()),
            StringComparer.OrdinalIgnoreCase);

        if (uidSet.Count == 0)
        {
            return 0;
        }

        var removed = _profiles.RemoveAll(profile => uidSet.Contains(profile.Uid));
        if (removed > 0)
        {
            Reindex();
            if (_profiles.Count == 0)
            {
                _nextProfile = 0;
            }
            else
            {
                _nextProfile %= _profiles.Count;
            }
        }

        return removed;
    }

    public string ExportText()
    {
        return string.Join(Environment.NewLine, _profiles.Select(profile => $"{profile.Uid}|{profile.Token}"));
    }

    public Dictionary<string, SavedProfileState> ExportStates()
    {
        return _profiles.ToDictionary(
            profile => profile.Uid,
            profile => new SavedProfileState
            {
                TokenStatus = profile.TokenStatus,
                TaskCount = profile.TaskCount,
                LastError = profile.LastError
            },
            StringComparer.OrdinalIgnoreCase);
    }

    public void ApplyStates(IReadOnlyDictionary<string, SavedProfileState>? states)
    {
        if (states is null || states.Count == 0)
        {
            return;
        }

        foreach (var profile in _profiles)
        {
            if (!states.TryGetValue(profile.Uid, out var state))
            {
                continue;
            }

            if (!string.IsNullOrWhiteSpace(state.TokenStatus))
            {
                profile.TokenStatus = state.TokenStatus;
            }

            profile.TaskCount = state.TaskCount;
            profile.LastError = state.LastError;
        }
    }

    public ProfileAccount? NextProfile()
    {
        if (_profiles.Count == 0)
        {
            return null;
        }

        var index = Interlocked.Increment(ref _nextProfile);
        return _profiles[(index - 1) % _profiles.Count];
    }

    public ProfileAccount? FindByUid(string uid)
    {
        return _profiles.FirstOrDefault(profile =>
            string.Equals(profile.Uid, uid.Trim(), StringComparison.OrdinalIgnoreCase));
    }

    private void Reindex()
    {
        for (var i = 0; i < _profiles.Count; i++)
        {
            _profiles[i].Index = i + 1;
        }
    }
}

public sealed record ParseResult(int Count, IReadOnlyList<string> Errors, int DuplicateCount, int AddedCount);
