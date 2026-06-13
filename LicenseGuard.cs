using System.Diagnostics;

namespace ToolEditDeleteCmt;

public static class LicenseGuard
{
    public static bool EnsureValid(IWin32Window owner, LicenseManager licenseManager, string actionName)
    {
        var result = ValidateRuntime(licenseManager);
        if (result.IsAllowed)
        {
            return true;
        }

        MessageBox.Show(
            owner,
            $"Không thể {actionName}.\n\n{result.Message}",
            "FlowMeta License",
            MessageBoxButtons.OK,
            MessageBoxIcon.Warning);
        return false;
    }

    public static bool ValidateRuntimeOrClose(Form owner, LicenseManager licenseManager)
    {
        var result = ValidateRuntime(licenseManager);
        if (result.IsAllowed)
        {
            return true;
        }

        MessageBox.Show(
            owner,
            $"License không còn hợp lệ. Tool sẽ đóng.\n\n{result.Message}",
            "FlowMeta License",
            MessageBoxButtons.OK,
            MessageBoxIcon.Warning);
        owner.Close();
        return false;
    }

    public static LicenseGuardResult ValidateRuntime(LicenseManager licenseManager)
    {
#if !DEBUG
        if (Debugger.IsAttached)
        {
            return new LicenseGuardResult(false, "Phát hiện debugger đang gắn vào ứng dụng.");
        }
#endif

        var status = licenseManager.GetCurrentStatus();
        if (!status.IsValid)
        {
            return new LicenseGuardResult(false, status.Message);
        }

        if (status.ExpiresAtUtc is null)
        {
            return new LicenseGuardResult(false, "License thiếu thời hạn sử dụng.");
        }

        if (status.ExpiresAtUtc.Value <= DateTimeOffset.UtcNow)
        {
            return new LicenseGuardResult(false, "License đã hết hạn.");
        }

        return new LicenseGuardResult(true, status.Message);
    }
}

public sealed record LicenseGuardResult(bool IsAllowed, string Message);
