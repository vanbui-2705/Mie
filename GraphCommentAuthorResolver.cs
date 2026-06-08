using System.Net;
using System.Text.Json;

namespace ToolEditDeleteCmt;

public sealed class GraphCommentAuthorResolver
{
    public async Task<GraphAuthorLookupResult> ResolveAuthorUidAsync(
        string commentLink,
        ProfileAccount checkerProfile,
        ProxyEndpoint? proxy,
        CancellationToken cancellationToken)
    {
        var commentId = FacebookGraphCommentService.ExtractCommentId(commentLink);
        if (string.IsNullOrWhiteSpace(commentId))
        {
            return new GraphAuthorLookupResult(null, "Khong parse duoc comment_id tu link.");
        }

        try
        {
            var uid = await ReadFromGraphAsync(commentId, checkerProfile.Token, proxy, cancellationToken);
            return string.IsNullOrWhiteSpace(uid)
                ? new GraphAuthorLookupResult(null, "Graph API khong tra ve from.id.")
                : new GraphAuthorLookupResult(uid, $"Lay UID bang Graph voi token check UID {checkerProfile.Uid}.");
        }
        catch (OperationCanceledException)
        {
            return new GraphAuthorLookupResult(null, "Da huy request check UID.");
        }
        catch (IOException ex) when (ex.Message.Contains("aborted", StringComparison.OrdinalIgnoreCase))
        {
            return new GraphAuthorLookupResult(null, "Request check UID bi huy.");
        }
        catch (Exception ex)
        {
            return new GraphAuthorLookupResult(null, ex.Message);
        }
    }

    private static async Task<string?> ReadFromGraphAsync(
        string commentId,
        string token,
        ProxyEndpoint? proxy,
        CancellationToken cancellationToken)
    {
        using var handler = CreateHandler(proxy);
        using var httpClient = new HttpClient(handler)
        {
            Timeout = TimeSpan.FromSeconds(35)
        };

        var url = $"https://graph.facebook.com/v19.0/{Uri.EscapeDataString(commentId)}?fields=id,from&access_token={Uri.EscapeDataString(token)}";
        using var response = await httpClient.GetAsync(url, cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(BuildGraphErrorMessage(response.StatusCode, body));
        }

        using var document = JsonDocument.Parse(body);
        var root = document.RootElement;
        if (root.TryGetProperty("from", out var from) &&
            from.TryGetProperty("id", out var id) &&
            id.ValueKind != JsonValueKind.Null)
        {
            var uid = id.ToString();
            return IsNumericUid(uid) ? uid : null;
        }

        return null;
    }

    private static HttpClientHandler CreateHandler(ProxyEndpoint? proxy)
    {
        if (proxy is null)
        {
            return new HttpClientHandler { UseProxy = false };
        }

        return new HttpClientHandler
        {
            UseProxy = true,
            Proxy = proxy.ToWebProxy()
        };
    }

    private static string BuildGraphErrorMessage(HttpStatusCode statusCode, string body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            if (document.RootElement.TryGetProperty("error", out var error))
            {
                var message = GetString(error, "message");
                var code = GetInt(error, "code");
                var subcode = GetInt(error, "error_subcode");
                return $"Graph read UID {(int)statusCode}: {message} (code {code}, subcode {subcode}).";
            }
        }
        catch
        {
        }

        body = body.Replace("\r", " ").Replace("\n", " ").Trim();
        return $"Graph read UID {(int)statusCode}: {(body.Length > 220 ? body[..220] : body)}";
    }

    private static string GetString(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null
            ? value.ToString()
            : "";
    }

    private static int GetInt(JsonElement element, string name)
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

    private static bool IsNumericUid(string value)
    {
        return value.Length is >= 5 and <= 30 && value.All(char.IsDigit);
    }
}

public sealed record GraphAuthorLookupResult(string? Uid, string Message);
