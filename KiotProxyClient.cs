using System.Net.Http.Json;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ToolEditDeleteCmt;

public sealed class KiotProxyClient
{
    private readonly HttpClient _httpClient;

    public KiotProxyClient()
    {
        _httpClient = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(20)
        };
    }

    public Task<ProxyEndpoint> GetNewProxyAsync(
        string apiKey,
        string authToken,
        string urlTemplate,
        CancellationToken cancellationToken)
    {
        return RequestProxyAsync(apiKey, authToken, urlTemplate, cancellationToken);
    }

    public Task<ProxyEndpoint> GetCurrentProxyAsync(
        string apiKey,
        string authToken,
        string urlTemplate,
        CancellationToken cancellationToken)
    {
        return RequestProxyAsync(apiKey, authToken, urlTemplate, cancellationToken);
    }

    private async Task<ProxyEndpoint> RequestProxyAsync(
        string apiKey,
        string authToken,
        string urlTemplate,
        CancellationToken cancellationToken)
    {
        var url = urlTemplate.Replace("{apiKey}", Uri.EscapeDataString(apiKey));
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        if (!string.IsNullOrWhiteSpace(authToken))
        {
            request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", authToken);
        }

        using var response = await _httpClient.SendAsync(request, cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(NormalizeErrorMessage(body, (int)response.StatusCode));
        }

        return ParseProxyResponse(body);
    }

    private static ProxyEndpoint ParseProxyResponse(string body)
    {
        using var document = ParseProxyJson(body);
        var root = document.RootElement;
        if (root.TryGetProperty("success", out var success) && success.ValueKind == JsonValueKind.False)
        {
            var message = TryGetString(root, "message") ?? "KiotProxy trả về success=false";
            throw new InvalidOperationException(NormalizeErrorMessage(root, message));
        }

        var data = root.TryGetProperty("data", out var dataElement) ? dataElement : root;
        var apiStatus = TryGetString(root, "status") ?? TryGetString(data, "status") ?? "";
        var apiMessage =
            TryGetString(root, "message") ??
            TryGetString(data, "message") ??
            TryGetString(root, "msg") ??
            TryGetString(data, "msg") ??
            "";
        var host = TryGetString(data, "host") ?? "";
        var port = TryGetInt(data, "httpPort");
        var username = TryGetString(data, "proxyUser");
        var password = TryGetString(data, "proxyPass");
        var http = TryGetString(data, "http") ?? TryGetString(data, "httpStaticProxy") ?? "";
        var expiresAt = TryGetProxyExpiresAt(data);

        if (string.IsNullOrWhiteSpace(host) || port <= 0)
        {
            var parsed = ParseProxyText(http);
            if (parsed is not null)
            {
                host = parsed.Host;
                port = parsed.HttpPort;
                username ??= parsed.Username;
                password ??= parsed.Password;
                expiresAt ??= parsed.ExpiresAt;
            }
        }

        if (string.IsNullOrWhiteSpace(host) || port <= 0)
        {
            throw new InvalidOperationException("Không tìm thấy host/httpPort trong phản hồi KiotProxy.");
        }

        return new ProxyEndpoint
        {
            Host = host,
            HttpPort = port,
            Username = username,
            Password = password,
            Display = !string.IsNullOrWhiteSpace(http) ? http : $"{host}:{port}",
            ExpiresAt = expiresAt,
            ApiStatus = apiStatus,
            ApiMessage = apiMessage
        };
    }

    private static JsonDocument ParseProxyJson(string body)
    {
        try
        {
            return JsonDocument.Parse(body);
        }
        catch (JsonException ex)
        {
            var message = NormalizeErrorMessage(body);
            throw new InvalidOperationException(
                string.IsNullOrWhiteSpace(message)
                    ? "KiotProxy tra ve phan hoi khong phai JSON."
                    : $"KiotProxy tra ve phan hoi khong phai JSON: {message}",
                ex);
        }
    }

    private static ProxyEndpoint? ParseProxyText(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        var text = value.Trim();
        if (text.StartsWith("http://", StringComparison.OrdinalIgnoreCase))
        {
            text = text["http://".Length..];
        }

        var parts = text.Split(':');
        if (parts.Length < 2 || !int.TryParse(parts[1], out var port))
        {
            return null;
        }

        return new ProxyEndpoint
        {
            Host = parts[0],
            HttpPort = port,
            Username = parts.Length >= 3 ? parts[2] : null,
            Password = parts.Length >= 4 ? string.Join(':', parts.Skip(3)) : null,
            Display = value
        };
    }

    private static DateTime? TryGetProxyExpiresAt(JsonElement element)
    {
        var now = DateTime.Now;
        DateTime? best = null;
        foreach (var candidate in EnumerateJsonProperties(element))
        {
            var name = candidate.Name;
            var value = candidate.Value;
            var parsed = TryParseExpiryValue(name, value, now);
            if (parsed is null)
            {
                continue;
            }

            if (parsed.Value > now && (best is null || parsed.Value < best.Value))
            {
                best = parsed.Value;
            }
        }

        return best;
    }

    private static IEnumerable<(string Name, JsonElement Value)> EnumerateJsonProperties(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in element.EnumerateObject())
            {
                yield return (property.Name, property.Value);
                foreach (var child in EnumerateJsonProperties(property.Value))
                {
                    yield return child;
                }
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in element.EnumerateArray())
            {
                foreach (var child in EnumerateJsonProperties(item))
                {
                    yield return child;
                }
            }
        }
    }

    private static DateTime? TryParseExpiryValue(string name, JsonElement value, DateTime now)
    {
        var normalizedName = Regex.Replace(name, "[^a-zA-Z]", "").ToLowerInvariant();
        var isChangeCooldown =
            normalizedName.Contains("change") ||
            normalizedName.Contains("next") ||
            normalizedName.Contains("request") ||
            normalizedName.Contains("retry") ||
            normalizedName.Contains("wait") ||
            normalizedName.Contains("cooldown");
        if (isChangeCooldown)
        {
            return null;
        }

        var isExpiryName =
            normalizedName.Contains("expire") ||
            normalizedName.Contains("expired") ||
            normalizedName.Contains("expiration") ||
            normalizedName.Contains("timeout") ||
            normalizedName.Contains("ttl") ||
            normalizedName.Contains("timelive") ||
            normalizedName.Contains("lifetime") ||
            normalizedName.Contains("timeleft") ||
            normalizedName.Contains("remain") ||
            normalizedName.Contains("duration");

        if (!isExpiryName)
        {
            return null;
        }

        if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number))
        {
            return ParseNumericExpiry(normalizedName, number, now);
        }

        if (value.ValueKind == JsonValueKind.String)
        {
            var text = value.GetString()?.Trim();
            if (string.IsNullOrWhiteSpace(text))
            {
                return null;
            }

            if (double.TryParse(text, out var textNumber))
            {
                return ParseNumericExpiry(normalizedName, textNumber, now);
            }

            if (DateTime.TryParse(text, out var dateTime))
            {
                return dateTime.Kind == DateTimeKind.Utc ? dateTime.ToLocalTime() : dateTime;
            }

            var duration = TryParseDurationText(text);
            if (duration is not null)
            {
                return now.Add(duration.Value);
            }
        }

        return null;
    }

    private static DateTime? ParseNumericExpiry(string normalizedName, double number, DateTime now)
    {
        if (number <= 0)
        {
            return null;
        }

        if (number > 10_000_000_000)
        {
            return DateTimeOffset.FromUnixTimeMilliseconds((long)number).LocalDateTime;
        }

        if (number > 1_000_000_000)
        {
            return DateTimeOffset.FromUnixTimeSeconds((long)number).LocalDateTime;
        }

        if (normalizedName.Contains("ms") ||
            normalizedName.Contains("millisecond") ||
            number > 86_400)
        {
            return now.AddMilliseconds(number);
        }

        if (normalizedName.Contains("minute") || normalizedName.Contains("min"))
        {
            return now.AddMinutes(number);
        }

        if (normalizedName.Contains("hour"))
        {
            return now.AddHours(number);
        }

        return now.AddSeconds(number);
    }

    private static TimeSpan? TryParseDurationText(string text)
    {
        var normalized = text.ToLowerInvariant();
        var hours = MatchDurationPart(normalized, @"(\d+)\s*(?:h|hour|hours|giờ|gio)");
        var minutes = MatchDurationPart(normalized, @"(\d+)\s*(?:m|min|mins|minute|minutes|phút|phut)");
        var seconds = MatchDurationPart(normalized, @"(\d+)\s*(?:s|sec|secs|second|seconds|giây|giay)");
        var total = TimeSpan.FromHours(hours) + TimeSpan.FromMinutes(minutes) + TimeSpan.FromSeconds(seconds);
        return total > TimeSpan.Zero ? total : null;
    }

    private static int MatchDurationPart(string text, string pattern)
    {
        var match = Regex.Match(text, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        return match.Success && int.TryParse(match.Groups[1].Value, out var value) ? value : 0;
    }

    private static string? TryGetString(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null
            ? value.ToString()
            : null;
    }

    private static int TryGetInt(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return 0;
        }

        return value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt32(out var number) => number,
            JsonValueKind.String when int.TryParse(value.GetString(), out var number) => number,
            _ => 0
        };
    }

    private static string TrimMessage(string value)
    {
        value = value.Replace("\r", " ").Replace("\n", " ").Trim();
        return value.Length > 180 ? value[..180] : value;
    }

    private static string NormalizeErrorMessage(string body, int? httpStatusCode = null)
    {
        var cleanBody = TrimMessage(body);
        try
        {
            using var document = JsonDocument.Parse(body);
            var root = document.RootElement;
            var message = TryGetString(root, "message") ?? cleanBody;
            var normalized = NormalizeErrorMessage(root, message);
            if (IsRetryDelayMessage(normalized))
            {
                return normalized;
            }

            return httpStatusCode is null
                ? normalized
                : $"KiotProxy HTTP {httpStatusCode}: {normalized}";
        }
        catch (JsonException)
        {
            var retryDelay = TryFormatRetryDelay(cleanBody);
            if (retryDelay is not null)
            {
                return retryDelay;
            }

            return httpStatusCode is null
                ? cleanBody
                : $"KiotProxy HTTP {httpStatusCode}: {cleanBody}";
        }
    }

    private static string NormalizeErrorMessage(JsonElement root, string message)
    {
        var retryAfter = TryGetInt(root, "retryAfter");
        retryAfter = retryAfter > 0 ? retryAfter : TryGetInt(root, "retry_after");
        if (retryAfter > 0)
        {
            return $"Gửi lại sau {retryAfter}s";
        }

        var retryDelay = TryFormatRetryDelay(message);
        if (retryDelay is not null)
        {
            return retryDelay;
        }

        return TrimMessage(message);
    }

    private static string? TryFormatRetryDelay(string value)
    {
        var match = Regex.Match(
            value,
            @"(?:Gửi lại sau|Gui lai sau|retry after|try again in)\s*(\d+)\s*(?:giây|giay|s|sec|secs|second|seconds)?",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        return match.Success ? $"Gửi lại sau {match.Groups[1].Value}s" : null;
    }

    private static bool IsRetryDelayMessage(string value)
    {
        return value.StartsWith("Gửi lại sau ", StringComparison.OrdinalIgnoreCase) &&
               value.EndsWith("s", StringComparison.OrdinalIgnoreCase);
    }
}
