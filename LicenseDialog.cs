namespace ToolEditDeleteCmt;

public sealed class LicenseDialog : Form
{
    private static readonly Color AppBackColor = Color.FromArgb(232, 241, 255);
    private static readonly Color PrimaryColor = Color.FromArgb(8, 102, 255);
    private static readonly Color DangerColor = Color.FromArgb(220, 38, 38);
    private static readonly Color TextColor = Color.FromArgb(17, 24, 39);
    private static readonly Font UiFont = new("Segoe UI", 9F);
    private static readonly Font UiFontBold = new("Segoe UI Semibold", 9F);

    private readonly LicenseManager _licenseManager;
    private readonly TextBox _licenseTextBox;
    private readonly Label _statusLabel;

    public LicenseDialog(LicenseManager licenseManager, LicenseStatus status)
    {
        _licenseManager = licenseManager;

        Text = "Kích hoạt FlowMeta";
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        ClientSize = new Size(640, 420);
        BackColor = AppBackColor;
        Font = UiFont;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 8,
            Padding = new Padding(16),
            BackColor = AppBackColor
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 6));

        var title = new Label
        {
            Dock = DockStyle.Fill,
            Text = "FlowMeta cần license key để sử dụng",
            Font = new Font("Segoe UI Semibold", 13F),
            ForeColor = TextColor,
            TextAlign = ContentAlignment.MiddleLeft
        };
        root.Controls.Add(title, 0, 0);

        _statusLabel = new Label
        {
            Dock = DockStyle.Fill,
            Text = status.Message,
            ForeColor = status.IsValid ? PrimaryColor : DangerColor,
            Font = UiFontBold,
            TextAlign = ContentAlignment.MiddleLeft
        };

        root.Controls.Add(CreateLabel("MachineID của máy này:"), 0, 1);
        var machinePanel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, BackColor = AppBackColor };
        machinePanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        machinePanel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        var machineTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            ReadOnly = true,
            Text = _licenseManager.MachineId,
            BorderStyle = BorderStyle.FixedSingle
        };
        var copyButton = CreateButton("Copy", PrimaryColor);
        copyButton.Click += (_, _) =>
        {
            try
            {
                Clipboard.SetText(_licenseManager.MachineId);
                _statusLabel.Text = "Đã copy MachineID.";
                _statusLabel.ForeColor = PrimaryColor;
            }
            catch
            {
                _statusLabel.Text = "Không copy được MachineID.";
                _statusLabel.ForeColor = DangerColor;
            }
        };
        machinePanel.Controls.Add(machineTextBox, 0, 0);
        machinePanel.Controls.Add(copyButton, 1, 0);
        root.Controls.Add(machinePanel, 0, 2);

        root.Controls.Add(CreateLabel("License key:"), 0, 3);
        _licenseTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            BorderStyle = BorderStyle.FixedSingle,
            PlaceholderText = "Dán license key do admin cấp"
        };
        root.Controls.Add(_licenseTextBox, 0, 4);

        root.Controls.Add(_statusLabel, 0, 5);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            BackColor = AppBackColor,
            Padding = new Padding(0, 6, 0, 0)
        };
        var exitButton = CreateButton("Thoát", DangerColor);
        exitButton.Click += (_, _) =>
        {
            DialogResult = DialogResult.Cancel;
            Close();
        };
        var activateButton = CreateButton("Kích hoạt", PrimaryColor);
        activateButton.Click += (_, _) => ActivateLicense();
        buttons.Controls.Add(exitButton);
        buttons.Controls.Add(activateButton);
        root.Controls.Add(buttons, 0, 6);

        Controls.Add(root);
        AcceptButton = activateButton;
        CancelButton = exitButton;
    }

    public static bool EnsureActivated(LicenseManager licenseManager)
    {
        var status = licenseManager.GetCurrentStatus();
        if (status.IsValid)
        {
            return true;
        }

        using var dialog = new LicenseDialog(licenseManager, status);
        return dialog.ShowDialog() == DialogResult.OK;
    }

    private void ActivateLicense()
    {
        var status = _licenseManager.ValidateAndSave(_licenseTextBox.Text);
        _statusLabel.Text = status.Message;
        _statusLabel.ForeColor = status.IsValid ? PrimaryColor : DangerColor;
        if (!status.IsValid)
        {
            return;
        }

        MessageBox.Show(status.Message, "Kích hoạt FlowMeta", MessageBoxButtons.OK, MessageBoxIcon.Information);
        DialogResult = DialogResult.OK;
        Close();
    }

    private static Label CreateLabel(string text)
    {
        return new Label
        {
            Dock = DockStyle.Fill,
            Text = text,
            ForeColor = TextColor,
            Font = UiFontBold,
            TextAlign = ContentAlignment.MiddleLeft
        };
    }

    private static Button CreateButton(string text, Color backColor)
    {
        return new RoundedButton
        {
            Text = text,
            Width = 110,
            Height = 34,
            BackColor = backColor,
            ForeColor = Color.White,
            ButtonColor = backColor,
            ButtonHoverColor = ControlPaint.Light(backColor),
            ButtonPressedColor = ControlPaint.Dark(backColor),
            ButtonBorderColor = ControlPaint.Dark(backColor),
            ButtonShadowColor = Color.FromArgb(80, ControlPaint.Dark(backColor)),
            Font = UiFontBold,
            Cursor = Cursors.Hand,
            UseVisualStyleBackColor = false,
            Margin = new Padding(8, 0, 0, 0)
        };
    }
}
