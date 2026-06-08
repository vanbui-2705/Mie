using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ToolEditDeleteCmt;

public sealed class CommentRequest
{
    public required ProfileAccount Profile { get; init; }
    public required string CommentLink { get; init; }
    public required CommentActionKind Action { get; init; }
    public string NewText { get; init; } = "";
    public string? ImagePath { get; init; }
    public ProxyEndpoint? Proxy { get; init; }
}

public sealed record TokenIssueInfo(string Kind, int Code, int Subcode, string Status);

public sealed record CommentResult(bool Success, string Message, string? OutputLink = null, TokenIssueInfo? TokenIssue = null);

public interface ICommentService
{
    Task<CommentResult> ExecuteAsync(CommentRequest request, CancellationToken cancellationToken);
}

public sealed class FacebookGraphCommentService : ICommentService
{
    public async Task<CommentResult> ExecuteAsync(CommentRequest request, CancellationToken cancellationToken)
    {
        try
        {
            using var handler = CreateHandler(request.Proxy);
            using var httpClient = new HttpClient(handler)
            {
                Timeout = TimeSpan.FromSeconds(45)
            };

            if (request.Action == CommentActionKind.NewComment)
            {
                var postId = ExtractPostId(request.CommentLink);
                return string.IsNullOrWhiteSpace(postId)
                    ? new CommentResult(false, "Khong parse duoc post id/link post.")
                    : await CreateCommentAsync(httpClient, postId, request.Profile.Token, request.NewText, request.ImagePath, cancellationToken);
            }

            var commentId = ExtractCommentId(request.CommentLink);
            if (string.IsNullOrWhiteSpace(commentId))
            {
                return new CommentResult(false, "Khong parse duoc comment_id tu link.");
            }

            return request.Action == CommentActionKind.Delete
                ? await DeleteAsync(httpClient, commentId, request.Profile.Token, cancellationToken)
                : await EditAsync(httpClient, commentId, request.Profile.Token, request.NewText, request.ImagePath, cancellationToken);
        }
        catch (OperationCanceledException)
        {
            return new CommentResult(false, "Tac vu da bi huy.");
        }
        catch (IOException ex) when (ex.Message.Contains("aborted", StringComparison.OrdinalIgnoreCase))
        {
            return new CommentResult(false, "Tac vu bi huy hoac ket noi bi ngat.");
        }
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

    private static async Task<CommentResult> EditAsync(
        HttpClient httpClient,
        string commentId,
        string token,
        string newText,
        string? imagePath,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(newText))
        {
            return new CommentResult(false, "Noi dung edit dang trong.");
        }

        var url = $"https://graph.facebook.com/{Uri.EscapeDataString(commentId)}";
        if (!string.IsNullOrWhiteSpace(imagePath) && File.Exists(imagePath))
        {
            return await EditWithImageAsync(httpClient, url, token, newText, imagePath, cancellationToken);
        }

        using var content = new FormUrlEncodedContent(new Dictionary<string, string>
        {
            ["message"] = newText,
            ["access_token"] = token
        });

        using var response = await httpClient.PostAsync(url, content, cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            return BuildGraphErrorResult(response.StatusCode, body);
        }

        return new CommentResult(true, "Da edit comment.");
    }

    private static async Task<CommentResult> EditWithImageAsync(
        HttpClient httpClient,
        string url,
        string token,
        string newText,
        string imagePath,
        CancellationToken cancellationToken)
    {
        await using var stream = File.OpenRead(imagePath);
        using var content = new MultipartFormDataContent();
        content.Add(new StringContent(newText), "message");
        content.Add(new StringContent(token), "access_token");

        var imageContent = new StreamContent(stream);
        imageContent.Headers.ContentType = new MediaTypeHeaderValue(GetImageContentType(imagePath));
        content.Add(imageContent, "source", Path.GetFileName(imagePath));

        using var response = await httpClient.PostAsync(url, content, cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            return BuildGraphErrorResult(response.StatusCode, body);
        }

        return new CommentResult(true, $"Da edit comment kem anh {Path.GetFileName(imagePath)}.");
    }

    private static async Task<CommentResult> DeleteAsync(
        HttpClient httpClient,
        string commentId,
        string token,
        CancellationToken cancellationToken)
    {
        var url = $"https://graph.facebook.com/{Uri.EscapeDataString(commentId)}?access_token={Uri.EscapeDataString(token)}";
        using var response = await httpClient.DeleteAsync(url, cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            return BuildGraphErrorResult(response.StatusCode, body);
        }

        return new CommentResult(true, "Da xoa comment.");
    }

    private static async Task<CommentResult> CreateCommentAsync(
        HttpClient httpClient,
        string postId,
        string token,
        string newText,
        string? imagePath,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(newText))
        {
            return new CommentResult(false, "Noi dung comment dang trong.");
        }

        var url = $"https://graph.facebook.com/{Uri.EscapeDataString(postId)}/comments";
        HttpContent content;
        FileStream? stream = null;
        try
        {
            if (!string.IsNullOrWhiteSpace(imagePath) && File.Exists(imagePath))
            {
                stream = File.OpenRead(imagePath);
                var multipart = new MultipartFormDataContent();
                multipart.Add(new StringContent(newText), "message");
                multipart.Add(new StringContent(token), "access_token");
                var imageContent = new StreamContent(stream);
                imageContent.Headers.ContentType = new MediaTypeHeaderValue(GetImageContentType(imagePath));
                multipart.Add(imageContent, "source", Path.GetFileName(imagePath));
                content = multipart;
            }
            else
            {
                content = new FormUrlEncodedContent(new Dictionary<string, string>
                {
                    ["message"] = newText,
                    ["access_token"] = token
                });
            }

            using (content)
            using (stream)
            {
                using var response = await httpClient.PostAsync(url, content, cancellationToken);
                var body = await response.Content.ReadAsStringAsync(cancellationToken);
                if (!response.IsSuccessStatusCode)
                {
                    return BuildGraphErrorResult(response.StatusCode, body);
                }

                var createdId = ExtractCreatedId(body);
                var link = BuildCommentLink(postId, createdId);
                var imageSuffix = !string.IsNullOrWhiteSpace(imagePath) && File.Exists(imagePath)
                    ? $" kem anh {Path.GetFileName(imagePath)}"
                    : "";
                return new CommentResult(true, $"Da tao comment moi{imageSuffix}.", link);
            }
        }
        catch
        {
            stream?.Dispose();
            throw;
        }
    }

    public static string? ExtractCommentId(string link)
    {
        var trimmed = link.Trim();
        if (string.IsNullOrWhiteSpace(trimmed))
        {
            return null;
        }

        if (!trimmed.StartsWith("http", StringComparison.OrdinalIgnoreCase))
        {
            return trimmed;
        }

        if (Uri.TryCreate(trimmed, UriKind.Absolute, out var uri))
        {
            var query = ParseQuery(uri.Query);
            foreach (var key in new[] { "comment_id", "commentid", "comment", "id" })
            {
                if (query.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value))
                {
                    return value;
                }
            }

            var pathMatch = Regex.Match(uri.AbsolutePath, @"(?:comment_id|comments?|reply_comment_id)[/=:-]([^/?#]+)", RegexOptions.IgnoreCase);
            if (pathMatch.Success)
            {
                return Uri.UnescapeDataString(pathMatch.Groups[1].Value);
            }
        }

        var fallbackMatch = Regex.Match(trimmed, @"comment_id[=:]([^&#\s]+)", RegexOptions.IgnoreCase);
        return fallbackMatch.Success ? Uri.UnescapeDataString(fallbackMatch.Groups[1].Value) : null;
    }

    public static string? ExtractPostId(string value)
    {
        var trimmed = value.Trim();
        if (string.IsNullOrWhiteSpace(trimmed))
        {
            return null;
        }

        if (!trimmed.StartsWith("http", StringComparison.OrdinalIgnoreCase))
        {
            return trimmed;
        }

        if (!Uri.TryCreate(trimmed, UriKind.Absolute, out var uri))
        {
            return null;
        }

        var query = ParseQuery(uri.Query);
        foreach (var key in new[] { "story_fbid", "fbid", "id" })
        {
            if (query.TryGetValue(key, out var queryValue) && !string.IsNullOrWhiteSpace(queryValue))
            {
                return queryValue;
            }
        }

        var path = uri.AbsolutePath.Trim('/');
        var postMatch = Regex.Match(path, @"(?:posts|videos|photos|permalink)/([^/?#]+)", RegexOptions.IgnoreCase);
        if (postMatch.Success)
        {
            return Uri.UnescapeDataString(postMatch.Groups[1].Value);
        }

        var pfbidMatch = Regex.Match(path, @"(pfbid[^/?#]+)", RegexOptions.IgnoreCase);
        return pfbidMatch.Success ? Uri.UnescapeDataString(pfbidMatch.Groups[1].Value) : null;
    }

    private static Dictionary<string, string> ParseQuery(string query)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var pair in query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var parts = pair.Split('=', 2);
            if (parts.Length == 2)
            {
                result[Uri.UnescapeDataString(parts[0])] = Uri.UnescapeDataString(parts[1]);
            }
        }

        return result;
    }

    private static string Trim(string value)
    {
        value = value.Replace("\r", " ").Replace("\n", " ").Trim();
        return value.Length > 240 ? value[..240] : value;
    }

    private static CommentResult BuildGraphErrorResult(HttpStatusCode statusCode, string body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            if (document.RootElement.TryGetProperty("error", out var error))
            {
                var message = GetString(error, "message");
                var code = GetInt(error, "code");
                var subcode = GetInt(error, "error_subcode");
                var userMessage = GetString(error, "error_user_msg");
                var hint = code switch
                {
                    200 => " Token khong co quyen voi comment nay, hoac comment khong thuoc UID/token dang dung.",
                    100 => " Sai ID/link post, post khong ton tai voi token nay, token khong co quyen doc/comment post, hoac ban dang nhap nham comment_id thay vi ID/link bai post.",
                    _ => ""
                };

                var fullMessage = $"Graph API {(int)statusCode}: {message} (code {code}, subcode {subcode}). {userMessage}{hint}".Trim();
                return new CommentResult(false, fullMessage, TokenIssue: DetectTokenIssue(message, userMessage, code, subcode));
            }
        }
        catch
        {
        }

        return new CommentResult(false, $"Graph API {(int)statusCode}: {Trim(body)}");
    }

    private static TokenIssueInfo? DetectTokenIssue(string message, string userMessage, int code, int subcode)
    {
        var issueCode = subcode != 0 ? subcode : code;
        var combined = $"{message} {userMessage}";
        var checkpointSubcodes = new HashSet<int> { 282, 459, 490, 492, 493, 494, 959 };
        if (checkpointSubcodes.Contains(code) ||
            checkpointSubcodes.Contains(subcode) ||
            combined.Contains("checkpoint", StringComparison.OrdinalIgnoreCase) ||
            combined.Contains("security check", StringComparison.OrdinalIgnoreCase) ||
            combined.Contains("verify", StringComparison.OrdinalIgnoreCase))
        {
            return new TokenIssueInfo("Checkpoint", code, subcode, issueCode != 0 ? $"Checkpoint {issueCode}" : "Checkpoint");
        }

        var tokenOutSubcodes = new HashSet<int> { 458, 460, 463, 467 };
        if (code == 190 ||
            tokenOutSubcodes.Contains(subcode) ||
            combined.Contains("access token", StringComparison.OrdinalIgnoreCase) && combined.Contains("expired", StringComparison.OrdinalIgnoreCase) ||
            combined.Contains("invalid oauth", StringComparison.OrdinalIgnoreCase) ||
            combined.Contains("error validating access token", StringComparison.OrdinalIgnoreCase) ||
            combined.Contains("session has expired", StringComparison.OrdinalIgnoreCase))
        {
            return new TokenIssueInfo("Token out", code, subcode, issueCode != 0 ? $"Token out {issueCode}" : "Token out");
        }

        return null;
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

    private static string GetImageContentType(string path)
    {
        return Path.GetExtension(path).ToLowerInvariant() switch
        {
            ".jpg" or ".jpeg" or ".jfif" or ".pjpeg" or ".pjp" => "image/jpeg",
            ".png" => "image/png",
            ".gif" => "image/gif",
            ".webp" => "image/webp",
            ".bmp" or ".dib" => "image/bmp",
            ".tif" or ".tiff" => "image/tiff",
            ".heic" => "image/heic",
            ".heif" => "image/heif",
            ".avif" => "image/avif",
            ".ico" => "image/x-icon",
            ".svg" => "image/svg+xml",
            _ => "application/octet-stream"
        };
    }

    private static string? ExtractCreatedId(string body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            return document.RootElement.TryGetProperty("id", out var id) ? id.ToString() : null;
        }
        catch
        {
            return null;
        }
    }

    private static string BuildCommentLink(string postId, string? commentId)
    {
        var normalizedCommentId = NormalizeCreatedCommentId(postId, commentId);
        return string.IsNullOrWhiteSpace(normalizedCommentId)
            ? $"https://www.facebook.com/{Uri.EscapeDataString(postId)}"
            : $"https://www.facebook.com/{Uri.EscapeDataString(postId)}?comment_id={Uri.EscapeDataString(normalizedCommentId)}";
    }

    private static string NormalizeCreatedCommentId(string postId, string? createdId)
    {
        if (string.IsNullOrWhiteSpace(createdId))
        {
            return "";
        }

        var id = createdId.Trim();
        var postPrefix = $"{postId.Trim()}_";
        if (id.StartsWith(postPrefix, StringComparison.OrdinalIgnoreCase))
        {
            return id[postPrefix.Length..];
        }

        var underscoreIndex = id.LastIndexOf('_');
        return underscoreIndex >= 0 && underscoreIndex < id.Length - 1
            ? id[(underscoreIndex + 1)..]
            : id;
    }
}
