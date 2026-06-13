namespace ToolEditDeleteCmt;

static class Program
{
    /// <summary>
    ///  The main entry point for the application.
    /// </summary>
    [STAThread]
    static void Main()
    {
        // To customize application configuration such as set high DPI settings or default font,
        // see https://aka.ms/applicationconfiguration.
        ApplicationConfiguration.Initialize();
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, e) =>
        {
            if (IsBenignAbort(e.Exception))
            {
                return;
            }

            MessageBox.Show(e.Exception.Message, "Lỗi", MessageBoxButtons.OK, MessageBoxIcon.Error);
        };
        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
        {
            if (e.ExceptionObject is Exception ex && IsBenignAbort(ex))
            {
                return;
            }
        };

        var updateChecker = new GitHubUpdateChecker();
        var startupUpdateCheck = CheckStartupNetworkAndUpdates(updateChecker);
        if (!startupUpdateCheck)
        {
            return;
        }

        var licenseManager = new LicenseManager();
        if (!LicenseDialog.EnsureActivated(licenseManager))
        {
            return;
        }

        var licenseGuard = LicenseGuard.ValidateRuntime(licenseManager);
        if (!licenseGuard.IsAllowed)
        {
            MessageBox.Show(
                licenseGuard.Message,
                "FlowMeta License",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning);
            return;
        }

        Application.Run(new Form1(licenseManager));

    }

    private static bool CheckStartupNetworkAndUpdates(GitHubUpdateChecker updateChecker)
    {
        try
        {
            var result = updateChecker.GetReleaseHistoryAsync().GetAwaiter().GetResult();
            if (!result.IsSuccess)
            {
                MessageBox.Show(
                    $"Không kiểm tra được mạng/cập nhật.\n\n{result.Message}\n\nVui lòng kết nối mạng rồi mở lại FlowMeta.",
                    "FlowMeta",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
                return false;
            }

            if (result.LatestUpdate is not null)
            {
                MessageBox.Show(
                    $"Có bản cập nhật mới: {result.LatestUpdate.TagName}\nPhiên bản hiện tại: {updateChecker.CurrentVersionText}\n\nBạn có thể cập nhật trong mục Cập nhật.",
                    "FlowMeta",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
            }

            return true;
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                $"Không có mạng hoặc không thể kết nối máy chủ cập nhật.\n\n{ex.Message}\n\nVui lòng kết nối mạng rồi mở lại FlowMeta.",
                "FlowMeta",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning);
            return false;
        }
    }

    private static bool IsBenignAbort(Exception exception)
    {
        return exception is OperationCanceledException ||
               exception is IOException io && io.Message.Contains("aborted", StringComparison.OrdinalIgnoreCase) ||
               exception.InnerException is not null && IsBenignAbort(exception.InnerException);
    }
}
