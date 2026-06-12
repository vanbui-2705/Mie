using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Win32;

namespace ToolEditDeleteCmt;

public sealed class LicenseManager
{
    private const string ProductName = "FlowMeta";
    private const string LicensePrefix = "FM1-";
    private const string PublicKeyXml =
        "<RSAKeyValue><Modulus>yv/kccMbiPIJ3R33+veL40gQidSwZNVRf4Q+aU7wxADSbIwhBXqRwgm7evFZxl3ujSw9gIBzRDbgjWj9tQW2dz8uiMYB/51yJu24fMvRfGUOclYtjUjT6AIHMa5uJ/Xb5HTbQymcKITv8Y70ZKUCwBEoPekiNRI0as72jiNzhPQHyuwA2oU/A40N3cAf/oiWMr1Lp4cdRonC/Pbid/Zd5hqK9MyKounX4jOWGbty21t2f9HvY1/Quls+YsTa0B8HpiKMLsQBtvLhLHBsqA0mTV7BEVoHWYitv0dduRI1fxGUNHCo2mAr+2HKgFvP82lJcRPCT9pfCX1/aE6W5U6l5Q==</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>";

    private readonly string _licensePath;

    public LicenseManager()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            ProductName);
        Directory.CreateDirectory(dir);
        _licensePath = Path.Combine(dir, "license.dpapi");
        MachineId = BuildMachineId();
    }

    public string MachineId { get; }

    public LicenseStatus GetCurrentStatus()
    {
        var key = LoadSavedLicenseKey();
        return string.IsNullOrWhiteSpace(key)
            ? LicenseStatus.Invalid(MachineId, "Chưa kích hoạt.")
            : Validate(key);
    }

    public LicenseStatus ValidateAndSave(string licenseKey)
    {
        var status = Validate(licenseKey);
        if (status.IsValid)
        {
            SaveLicenseKey(licenseKey);
        }

        return status;
    }

    public LicenseStatus Validate(string licenseKey)
    {
        try
        {
            var normalized = NormalizeLicenseKey(licenseKey);
            if (string.IsNullOrWhiteSpace(normalized))
            {
                return LicenseStatus.Invalid(MachineId, "Chưa nhập license key.");
            }

            if (!normalized.StartsWith(LicensePrefix, StringComparison.Ordinal))
            {
                return LicenseStatus.Invalid(MachineId, "License key sai định dạng.");
            }

            var body = normalized[LicensePrefix.Length..];
            var parts = body.Split('.', 2);
            if (parts.Length != 2)
            {
                return LicenseStatus.Invalid(MachineId, "License key sai định dạng.");
            }

            var payloadBytes = DecodeBase64Url(parts[0]);
            var signatureBytes = DecodeBase64Url(parts[1]);
            using var rsa = RSA.Create();
            rsa.FromXmlString(PublicKeyXml);
            var signatureValid = rsa.VerifyData(
                payloadBytes,
                signatureBytes,
                HashAlgorithmName.SHA256,
                RSASignaturePadding.Pkcs1);
            if (!signatureValid)
            {
                return LicenseStatus.Invalid(MachineId, "Chữ ký license không hợp lệ.");
            }

            var payload = JsonSerializer.Deserialize<LicensePayload>(payloadBytes);
            if (payload is null)
            {
                return LicenseStatus.Invalid(MachineId, "Không đọc được dữ liệu license.");
            }

            if (!string.Equals(payload.Product, ProductName, StringComparison.OrdinalIgnoreCase))
            {
                return LicenseStatus.Invalid(MachineId, "License không đúng sản phẩm.");
            }

            if (!string.Equals(payload.MachineId, MachineId, StringComparison.OrdinalIgnoreCase))
            {
                return LicenseStatus.Invalid(MachineId, "License không đúng MachineID của máy này.");
            }

            if (payload.ExpiresAtUtc <= DateTimeOffset.UtcNow)
            {
                return LicenseStatus.Invalid(
                    MachineId,
                    $"License đã hết hạn lúc {payload.ExpiresAtUtc.ToLocalTime():dd/MM/yyyy HH:mm}.",
                    payload.ExpiresAtUtc,
                    payload.LicenseId);
            }

            return LicenseStatus.Valid(
                MachineId,
                payload.ExpiresAtUtc,
                payload.LicenseId,
                $"License hợp lệ đến {payload.ExpiresAtUtc.ToLocalTime():dd/MM/yyyy HH:mm}.");
        }
        catch
        {
            return LicenseStatus.Invalid(MachineId, "License key không hợp lệ.");
        }
    }

    private string? LoadSavedLicenseKey()
    {
        if (!File.Exists(_licensePath))
        {
            return null;
        }

        try
        {
            var protectedBytes = File.ReadAllBytes(_licensePath);
            var bytes = ProtectedData.Unprotect(protectedBytes, null, DataProtectionScope.CurrentUser);
            return Encoding.UTF8.GetString(bytes);
        }
        catch
        {
            return null;
        }
    }

    private void SaveLicenseKey(string licenseKey)
    {
        var bytes = Encoding.UTF8.GetBytes(NormalizeLicenseKey(licenseKey));
        var protectedBytes = ProtectedData.Protect(bytes, null, DataProtectionScope.CurrentUser);
        File.WriteAllBytes(_licensePath, protectedBytes);
    }

    private static string NormalizeLicenseKey(string licenseKey)
    {
        return licenseKey
            .Replace("\r", "", StringComparison.Ordinal)
            .Replace("\n", "", StringComparison.Ordinal)
            .Replace(" ", "", StringComparison.Ordinal)
            .Trim();
    }

    private static string BuildMachineId()
    {
        var rawMachineId = ReadWindowsMachineGuid();
        if (string.IsNullOrWhiteSpace(rawMachineId))
        {
            rawMachineId = $"{Environment.MachineName}|{Environment.UserDomainName}";
        }

        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes($"{ProductName}|{rawMachineId}"));
        var hex = Convert.ToHexString(bytes)[..32];
        return $"FM-{hex[..8]}-{hex[8..16]}-{hex[16..24]}-{hex[24..32]}";
    }

    private static string? ReadWindowsMachineGuid()
    {
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Cryptography");
            return key?.GetValue("MachineGuid")?.ToString();
        }
        catch
        {
            return null;
        }
    }

    private static byte[] DecodeBase64Url(string value)
    {
        var base64 = value.Replace('-', '+').Replace('_', '/');
        var padding = base64.Length % 4;
        if (padding > 0)
        {
            base64 = base64.PadRight(base64.Length + 4 - padding, '=');
        }

        return Convert.FromBase64String(base64);
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

public sealed record LicenseStatus(
    bool IsValid,
    string MachineId,
    DateTimeOffset? ExpiresAtUtc,
    string LicenseId,
    string Message)
{
    public static LicenseStatus Valid(string machineId, DateTimeOffset expiresAtUtc, string licenseId, string message)
    {
        return new LicenseStatus(true, machineId, expiresAtUtc, licenseId, message);
    }

    public static LicenseStatus Invalid(
        string machineId,
        string message,
        DateTimeOffset? expiresAtUtc = null,
        string? licenseId = null)
    {
        return new LicenseStatus(false, machineId, expiresAtUtc, licenseId ?? "", message);
    }
}
