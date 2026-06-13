namespace ToolEditDeleteCmt;

public static class NetworkGuard
{
    private static readonly Uri[] CheckUris =
    [
        new("https://www.gstatic.com/generate_204"),
        new("https://www.msftconnecttest.com/connecttest.txt")
    ];

    public static async Task<bool> HasInternetAsync(CancellationToken cancellationToken = default)
    {
        foreach (var uri in CheckUris)
        {
            try
            {
                using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
                using var request = new HttpRequestMessage(HttpMethod.Get, uri);
                using var response = await client.SendAsync(request, cancellationToken);
                if (response.IsSuccessStatusCode || (int)response.StatusCode == 204)
                {
                    return true;
                }
            }
            catch
            {
            }
        }

        return false;
    }
}
