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
        var licenseManager = new LicenseManager();
        if (!LicenseDialog.EnsureActivated(licenseManager))
        {
            return;
        }

        Application.Run(new Form1(licenseManager));

    }

    private static bool IsBenignAbort(Exception exception)
    {
        return exception is OperationCanceledException ||
               exception is IOException io && io.Message.Contains("aborted", StringComparison.OrdinalIgnoreCase) ||
               exception.InnerException is not null && IsBenignAbort(exception.InnerException);
    }
}
