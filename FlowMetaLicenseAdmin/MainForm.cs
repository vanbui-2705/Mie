namespace FlowMetaLicenseAdmin;

public sealed class MainForm : Form
{
    private static readonly Color BackColorValue = Color.FromArgb(225, 245, 249);
    private static readonly Color PrimaryColor = Color.FromArgb(0, 174, 239);
    private static readonly Color DangerColor = Color.FromArgb(220, 38, 38);
    private static readonly Color TextColor = Color.FromArgb(17, 24, 39);
    private static readonly Font UiFont = new("Segoe UI", 9F);
    private static readonly Font UiFontBold = new("Segoe UI Semibold", 9F);

    private readonly AdminPrivateKeyStore _privateKeyStore = new();
    private readonly TextBox _privateKeyTextBox = new();
    private readonly TextBox _machineIdTextBox = new();
    private readonly DateTimePicker _expiryPicker = new();
    private readonly ComboBox _presetComboBox = new();
    private readonly TextBox _licenseKeyTextBox = new();
    private readonly Label _statusLabel = new();
    private Button _togglePrivateKeyButton = null!;
    private bool _privateKeyVisible;

    public MainForm()
    {
        Text = "FlowMeta License Admin";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(900, 700);
        Size = new Size(980, 760);
        Font = UiFont;
        BackColor = BackColorValue;
        ApplyIcon();
        BuildUi();
        _privateKeyTextBox.Text = _privateKeyStore.Load();
        SetPrivateKeyVisible(false);
        ConfigurePresets();
        SetStatus(string.IsNullOrWhiteSpace(_privateKeyTextBox.Text)
            ? "Chưa có private key đã lưu. Hãy nhập hoặc import license-private.key."
            : $"Đã tải private key đã lưu: {_privateKeyStore.PathDisplay}", TextColor);
    }

    private void ApplyIcon()
    {
        try
        {
            var icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            if (icon is not null)
            {
                Icon = icon;
            }
        }
        catch
        {
        }
    }

    private void BuildUi()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 7,
            Padding = new Padding(16),
            BackColor = BackColorValue
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 176));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 74));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 74));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));

        var title = new Label
        {
            Dock = DockStyle.Fill,
            Text = "Tạo license FlowMeta",
            ForeColor = TextColor,
            Font = new Font("Segoe UI Semibold", 15F),
            TextAlign = ContentAlignment.MiddleLeft
        };
        root.Controls.Add(title, 0, 0);

        root.Controls.Add(BuildPrivateKeySection(), 0, 1);
        root.Controls.Add(BuildMachineIdRow(), 0, 2);
        root.Controls.Add(BuildExpiryRow(), 0, 3);

        _licenseKeyTextBox.Dock = DockStyle.Fill;
        _licenseKeyTextBox.Multiline = true;
        _licenseKeyTextBox.ScrollBars = ScrollBars.Both;
        _licenseKeyTextBox.WordWrap = false;
        _licenseKeyTextBox.BorderStyle = BorderStyle.FixedSingle;
        _licenseKeyTextBox.PlaceholderText = "License key sẽ hiện tại đây";
        root.Controls.Add(WrapWithLabel("License key:", _licenseKeyTextBox), 0, 4);

        _statusLabel.Dock = DockStyle.Fill;
        _statusLabel.ForeColor = TextColor;
        _statusLabel.Font = UiFontBold;
        _statusLabel.TextAlign = ContentAlignment.MiddleLeft;
        root.Controls.Add(_statusLabel, 0, 5);

        root.Controls.Add(BuildButtons(), 0, 6);
        Controls.Add(root);
    }

    private Control BuildPrivateKeySection()
    {
        var section = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, ColumnCount = 1, BackColor = BackColorValue };
        section.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        section.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var header = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 5, BackColor = BackColorValue };
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        header.Controls.Add(new Label
        {
            Dock = DockStyle.Fill,
            Text = "Private key admin:",
            TextAlign = ContentAlignment.MiddleLeft,
            ForeColor = TextColor,
            Font = UiFontBold
        }, 0, 0);

        var importButton = CreateButton("Nhập key", 100, PrimaryColor);
        importButton.Click += (_, _) => ImportPrivateKey();
        var saveButton = CreateButton("Lưu key", 100, PrimaryColor);
        saveButton.Click += (_, _) => SavePrivateKey();
        _togglePrivateKeyButton = CreateButton("Hiện", 100, PrimaryColor);
        _togglePrivateKeyButton.Click += (_, _) => SetPrivateKeyVisible(!_privateKeyVisible);
        var clearButton = CreateButton("Xóa key", 100, DangerColor);
        clearButton.Click += (_, _) => ClearSavedPrivateKey();

        header.Controls.Add(importButton, 1, 0);
        header.Controls.Add(saveButton, 2, 0);
        header.Controls.Add(_togglePrivateKeyButton, 3, 0);
        header.Controls.Add(clearButton, 4, 0);
        section.Controls.Add(header, 0, 0);

        _privateKeyTextBox.Dock = DockStyle.Fill;
        _privateKeyTextBox.Multiline = true;
        _privateKeyTextBox.ScrollBars = ScrollBars.Both;
        _privateKeyTextBox.WordWrap = false;
        _privateKeyTextBox.BorderStyle = BorderStyle.FixedSingle;
        _privateKeyTextBox.PlaceholderText = "Dán nội dung license-private.key vào đây, hoặc bấm Nhập key";
        section.Controls.Add(_privateKeyTextBox, 0, 1);
        return section;
    }

    private Control BuildMachineIdRow()
    {
        _machineIdTextBox.Dock = DockStyle.Fill;
        _machineIdTextBox.BorderStyle = BorderStyle.FixedSingle;
        _machineIdTextBox.PlaceholderText = "FM-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX";
        return WrapWithLabel("MachineID người dùng gửi:", _machineIdTextBox);
    }

    private Control BuildExpiryRow()
    {
        _expiryPicker.Dock = DockStyle.Left;
        _expiryPicker.Width = 220;
        _expiryPicker.Format = DateTimePickerFormat.Custom;
        _expiryPicker.CustomFormat = "yyyy-MM-dd HH:mm:ss";
        _expiryPicker.Value = DateTime.Now.AddDays(30);

        _presetComboBox.Dock = DockStyle.Left;
        _presetComboBox.Width = 180;
        _presetComboBox.DropDownStyle = ComboBoxStyle.DropDownList;

        var panel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            BackColor = BackColorValue,
            WrapContents = false
        };
        panel.Controls.Add(_expiryPicker);
        panel.Controls.Add(new Label
        {
            Text = "Chọn nhanh:",
            Width = 95,
            Height = 26,
            TextAlign = ContentAlignment.MiddleRight,
            ForeColor = TextColor,
            Font = UiFontBold,
            Margin = new Padding(16, 0, 8, 0)
        });
        panel.Controls.Add(_presetComboBox);
        return WrapWithLabel("Hạn sử dụng:", panel);
    }

    private void ConfigurePresets()
    {
        _presetComboBox.Items.AddRange(["1 ngày", "7 ngày", "30 ngày", "90 ngày", "365 ngày"]);
        _presetComboBox.SelectedIndex = 2;
        _presetComboBox.SelectedIndexChanged += (_, _) =>
        {
            var days = _presetComboBox.SelectedItem?.ToString() switch
            {
                "1 ngày" => 1,
                "7 ngày" => 7,
                "30 ngày" => 30,
                "90 ngày" => 90,
                "365 ngày" => 365,
                _ => 30
            };
            _expiryPicker.Value = DateTime.Now.AddDays(days);
        };
    }

    private Control BuildButtons()
    {
        var panel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            BackColor = BackColorValue,
            Padding = new Padding(0, 7, 0, 0)
        };

        var clearButton = CreateButton("Xóa", 100, DangerColor);
        clearButton.Click += (_, _) => ClearInputs();
        var copyButton = CreateButton("Copy key", 110, PrimaryColor);
        copyButton.Click += (_, _) => CopyLicenseKey();
        var generateButton = CreateButton("Tạo key", 110, PrimaryColor);
        generateButton.Click += (_, _) => GenerateLicenseKey();
        panel.Controls.Add(clearButton);
        panel.Controls.Add(copyButton);
        panel.Controls.Add(generateButton);
        return panel;
    }

    private static Control WrapWithLabel(string labelText, Control content)
    {
        var panel = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, ColumnCount = 1, BackColor = BackColorValue };
        panel.RowStyles.Add(new RowStyle(SizeType.Absolute, 26));
        panel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        panel.Controls.Add(new Label
        {
            Dock = DockStyle.Fill,
            Text = labelText,
            TextAlign = ContentAlignment.MiddleLeft,
            ForeColor = TextColor,
            Font = UiFontBold
        }, 0, 0);
        panel.Controls.Add(content, 0, 1);
        return panel;
    }

    private static Button CreateButton(string text, int width, Color color)
    {
        return new Button
        {
            Text = text,
            Width = width,
            Height = 30,
            BackColor = color,
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            Font = UiFontBold,
            Cursor = Cursors.Hand,
            Margin = new Padding(8, 0, 0, 0),
            UseVisualStyleBackColor = false
        };
    }

    private void SetPrivateKeyVisible(bool visible)
    {
        _privateKeyVisible = visible;
        _togglePrivateKeyButton.Text = visible ? "Ẩn" : "Hiện";
        _privateKeyTextBox.UseSystemPasswordChar = !visible;
    }

    private void ImportPrivateKey()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Chọn license-private.key",
            Filter = "File key (*.key)|*.key|Tất cả file (*.*)|*.*",
            FileName = "license-private.key"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }

        _privateKeyTextBox.Text = File.ReadAllText(dialog.FileName);
        SetStatus("Đã nhập private key. Bấm Lưu key để lưu mã hóa vào máy admin.", PrimaryColor);
    }

    private void SavePrivateKey()
    {
        try
        {
            _privateKeyStore.Save(_privateKeyTextBox.Text);
            SetStatus($"Đã lưu private key mã hóa: {_privateKeyStore.PathDisplay}", PrimaryColor);
        }
        catch (Exception ex)
        {
            SetStatus(ex.Message, DangerColor);
            MessageBox.Show(this, ex.Message, "FlowMeta License Admin", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void ClearSavedPrivateKey()
    {
        var confirm = MessageBox.Show(
            this,
            "Xóa private key đã lưu trên máy admin?",
            "FlowMeta License Admin",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question);
        if (confirm != DialogResult.Yes)
        {
            return;
        }

        _privateKeyStore.Clear();
        _privateKeyTextBox.Clear();
        SetStatus("Đã xóa private key đã lưu.", DangerColor);
    }

    private void GenerateLicenseKey()
    {
        try
        {
            _licenseKeyTextBox.Text = LicenseKeyGenerator.Generate(
                _machineIdTextBox.Text,
                _expiryPicker.Value,
                _privateKeyTextBox.Text);
            SetStatus("Đã tạo license key.", PrimaryColor);
        }
        catch (Exception ex)
        {
            SetStatus(ex.Message, DangerColor);
            MessageBox.Show(this, ex.Message, "FlowMeta License Admin", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void CopyLicenseKey()
    {
        if (string.IsNullOrWhiteSpace(_licenseKeyTextBox.Text))
        {
            SetStatus("Chưa có license key để copy.", DangerColor);
            return;
        }

        Clipboard.SetText(_licenseKeyTextBox.Text);
        SetStatus("Đã copy license key.", PrimaryColor);
    }

    private void ClearInputs()
    {
        _machineIdTextBox.Clear();
        _licenseKeyTextBox.Clear();
        SetStatus("Đã xóa MachineID và license key.", TextColor);
    }

    private void SetStatus(string message, Color color)
    {
        _statusLabel.Text = message;
        _statusLabel.ForeColor = color;
    }
}
