using System.Security.Cryptography;
using System.Text;

namespace FlowMetaLicenseAdmin;

internal sealed class AdminPrivateKeyStore
{
    private readonly string _path;

    public AdminPrivateKeyStore()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "FlowMetaLicenseAdmin");
        Directory.CreateDirectory(dir);
        _path = Path.Combine(dir, "private-key.dpapi");
    }

    public string PathDisplay => _path;

    public string Load()
    {
        if (!File.Exists(_path))
        {
            return "";
        }

        try
        {
            var protectedBytes = File.ReadAllBytes(_path);
            var bytes = ProtectedData.Unprotect(protectedBytes, null, DataProtectionScope.CurrentUser);
            return Encoding.UTF8.GetString(bytes);
        }
        catch
        {
            return "";
        }
    }

    public void Save(string privateKey)
    {
        var bytes = Encoding.UTF8.GetBytes(privateKey.Trim());
        var protectedBytes = ProtectedData.Protect(bytes, null, DataProtectionScope.CurrentUser);
        File.WriteAllBytes(_path, protectedBytes);
    }

    public void Clear()
    {
        if (File.Exists(_path))
        {
            File.Delete(_path);
        }
    }
}
