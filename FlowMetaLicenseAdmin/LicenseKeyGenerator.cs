using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace FlowMetaLicenseAdmin;

internal static class LicenseKeyGenerator
{
    private const string ProductName = "FlowMeta";

    public static string Generate(string machineId, DateTime expiresLocal, string privateKeyXml)
    {
        var normalizedMachineId = machineId.Trim().ToUpperInvariant();
        if (string.IsNullOrWhiteSpace(normalizedMachineId))
        {
            throw new InvalidOperationException("Chưa nhập MachineID.");
        }

        if (!System.Text.RegularExpressions.Regex.IsMatch(
                normalizedMachineId,
                @"^FM-[A-Z0-9]{8}-[A-Z0-9]{8}-[A-Z0-9]{8}-[A-Z0-9]{8}$"))
        {
            throw new InvalidOperationException("MachineID sai định dạng.");
        }

        if (string.IsNullOrWhiteSpace(privateKeyXml))
        {
            throw new InvalidOperationException("Chưa nhập private key.");
        }

        var expiresAtUtc = new DateTimeOffset(expiresLocal).ToUniversalTime();
        if (expiresAtUtc <= DateTimeOffset.UtcNow)
        {
            throw new InvalidOperationException("Hạn sử dụng phải lớn hơn thời gian hiện tại.");
        }

        var payload = new LicensePayload
        {
            Product = ProductName,
            MachineId = normalizedMachineId,
            IssuedAtUtc = DateTimeOffset.UtcNow,
            ExpiresAtUtc = expiresAtUtc,
            LicenseId = Guid.NewGuid().ToString("N")
        };

        var json = JsonSerializer.Serialize(payload);
        var payloadBytes = Encoding.UTF8.GetBytes(json);
        using var rsa = RSA.Create();
        rsa.FromXmlString(privateKeyXml.Trim());
        var signatureBytes = rsa.SignData(payloadBytes, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        return $"FM1-{ToBase64Url(payloadBytes)}.{ToBase64Url(signatureBytes)}";
    }

    private static string ToBase64Url(byte[] bytes)
    {
        return Convert.ToBase64String(bytes)
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');
    }

    private sealed class LicensePayload
    {
        public string Product { get; set; } = "";
        public string MachineId { get; set; } = "";
        public DateTimeOffset IssuedAtUtc { get; set; }
        public DateTimeOffset ExpiresAtUtc { get; set; }
        public string LicenseId { get; set; } = "";
    }
}
