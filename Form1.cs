namespace ToolEditDeleteCmt;

public partial class Form1 : Form
{
    private static readonly Color AppBackColor = Color.FromArgb(236, 254, 255);
    private static readonly Color PanelBackColor = Color.White;
    private static readonly Color BorderColor = Color.FromArgb(165, 243, 252);
    private static readonly Color PrimaryColor = Color.FromArgb(6, 182, 212);
    private static readonly Color PrimaryDarkColor = Color.FromArgb(8, 145, 178);
    private static readonly Color PrimarySoftColor = Color.FromArgb(207, 250, 254);
    private static readonly Color SuccessColor = Color.FromArgb(22, 163, 74);
    private static readonly Color WarningColor = Color.FromArgb(217, 119, 6);
    private static readonly Color DangerColor = Color.FromArgb(220, 38, 38);
    private static readonly Color TextColor = Color.FromArgb(17, 24, 39);
    private static readonly Font UiFont = new("Segoe UI", 9F);
    private static readonly Font UiFontBold = new("Segoe UI Semibold", 9F);
    private static readonly Font MonoFont = new("Consolas", 9.5F);

    private readonly SecureSettingsStore _settingsStore = new();
    private readonly ProfileManager _profileManager = new();
    private readonly ProxyManager _proxyManager = new();
    private readonly CommentTaskManager _taskManager;
    private readonly Dictionary<string, DataGridViewRow> _logRowsByKey = new(StringComparer.OrdinalIgnoreCase);
    private AppSettings _settings;
    private bool _tasksStoppedByUser;

    private TextBox _profileTextBox = null!;
    private DataGridView _profileGrid = null!;
    private Button _checkTokensButton = null!;
    private TextBox _uidsTextBox = null!;
    private TextBox _linksTextBox = null!;
    private TextBox _postIdTextBox = null!;
    private Label _uidCountLabel = null!;
    private Label _linkCountLabel = null!;
    private Label _postCountLabel = null!;
    private ComboBox _actionCombo = null!;
    private NumericUpDown _threadsInput = null!;
    private NumericUpDown _delayMinInput = null!;
    private NumericUpDown _delayMaxInput = null!;
    private NumericUpDown _delayEveryRoundsInput = null!;
    private NumericUpDown _postsPerUidInput = null!;
    private TextBox _editTextBox = null!;
    private TextBox _imageFolderTextBox = null!;
    private Label _statsLabel = null!;
    private DataGridView _logGrid = null!;
    private Button _startTasksButton = null!;
    private Button _stopTasksButton = null!;
    private Button _startProxyButton = null!;
    private Button _stopProxyButton = null!;
    private TextBox _kiotAuthTokenTextBox = null!;
    private TextBox _proxyKeysTextBox = null!;
    private TextBox _getNewProxyUrlTextBox = null!;
    private TextBox _getCurrentProxyUrlTextBox = null!;
    private NumericUpDown _usesPerProxyInput = null!;
    private DataGridView _proxyGrid = null!;

    public Form1()
    {
        _settings = _settingsStore.Load();
        _taskManager = new CommentTaskManager(
            _profileManager,
            _proxyManager,
            new FacebookGraphCommentService(),
            new GraphCommentAuthorResolver());
        InitializeComponent();
        WireEvents();
        LoadSettingsIntoUi();
        _proxyManager.Configure(_settings);
        RefreshProxyGrid();
    }

    private void InitializeComponent()
    {
        Text = "Công cụ quản lý comment";
        ApplyAppIcon();
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(1180, 760);
        Size = new Size(1280, 820);
        Font = UiFont;
        BackColor = AppBackColor;

        var tabs = new TabControl
        {
            Dock = DockStyle.Fill,
            Font = UiFontBold,
            Padding = new Point(14, 5)
        };
        tabs.TabPages.Add(BuildProfileTab());
        tabs.TabPages.Add(BuildInteractionTab());
        tabs.TabPages.Add(BuildProxyTab());
        Controls.Add(tabs);
    }

    private void ApplyAppIcon()
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

    private static Label CreateLabel(string text)
    {
        return new Label
        {
            Text = text,
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            ForeColor = TextColor,
            BackColor = AppBackColor,
            Font = UiFontBold
        };
    }

    private static Panel CreateHeaderWithCount(string text, Label countLabel)
    {
        var panel = new Panel
        {
            Dock = DockStyle.Fill,
            BackColor = AppBackColor,
            Margin = new Padding(0, 0, 8, 0)
        };
        var title = CreateLabel(text);
        title.Dock = DockStyle.Left;
        title.AutoSize = true;
        countLabel.Dock = DockStyle.Right;
        panel.Controls.Add(countLabel);
        panel.Controls.Add(title);
        return panel;
    }

    private static Label CreateCountLabel()
    {
        return new Label
        {
            AutoSize = true,
            Text = "0",
            TextAlign = ContentAlignment.MiddleRight,
            ForeColor = PrimaryDarkColor,
            BackColor = PrimarySoftColor,
            Font = UiFontBold,
            Padding = new Padding(8, 2, 8, 2),
            Margin = new Padding(0)
        };
    }

    private static Button CreateButton(
        string text,
        int width = 110,
        Color? backColor = null,
        DockStyle dock = DockStyle.None)
    {
        var baseColor = backColor ?? PrimaryColor;
        var button = new RoundedButton
        {
            Text = text,
            Width = width,
            Height = 34,
            Dock = dock,
            BackColor = baseColor,
            ForeColor = Color.White,
            Font = UiFontBold,
            Margin = new Padding(0, 0, 8, 0),
            Cursor = Cursors.Hand,
            UseVisualStyleBackColor = false,
            ButtonColor = baseColor,
            ButtonHoverColor = ControlPaint.Light(baseColor),
            ButtonPressedColor = ControlPaint.Dark(baseColor),
            ButtonBorderColor = ControlPaint.Dark(baseColor),
            ButtonShadowColor = Color.FromArgb(80, ControlPaint.Dark(baseColor))
        };
        return button;
    }

    private static void SetButtonRunning(Button button, bool running)
    {
        if (running)
        {
            if (button is RoundedButton runningButton)
            {
                runningButton.ButtonColor = Color.FromArgb(156, 163, 175);
                runningButton.ButtonHoverColor = Color.FromArgb(156, 163, 175);
                runningButton.ButtonPressedColor = Color.FromArgb(107, 114, 128);
                runningButton.ButtonBorderColor = Color.FromArgb(107, 114, 128);
                runningButton.ButtonShadowColor = Color.FromArgb(70, 107, 114, 128);
            }

            button.Enabled = false;
            button.BackColor = Color.FromArgb(156, 163, 175);
            button.ForeColor = Color.White;
            return;
        }

        if (button is RoundedButton normalButton)
        {
            normalButton.ButtonColor = PrimaryColor;
            normalButton.ButtonHoverColor = ControlPaint.Light(PrimaryColor);
            normalButton.ButtonPressedColor = ControlPaint.Dark(PrimaryColor);
            normalButton.ButtonBorderColor = PrimaryDarkColor;
            normalButton.ButtonShadowColor = Color.FromArgb(80, PrimaryDarkColor);
        }

        button.Enabled = true;
        button.BackColor = PrimaryColor;
        button.ForeColor = Color.White;
    }

    private static void StyleTextBox(TextBox textBox)
    {
        textBox.BorderStyle = BorderStyle.FixedSingle;
        textBox.BackColor = PanelBackColor;
        textBox.ForeColor = TextColor;
        textBox.Margin = new Padding(0, 2, 8, 6);
    }

    private static void StyleComboBox(ComboBox comboBox)
    {
        comboBox.FlatStyle = FlatStyle.Flat;
        comboBox.BackColor = PanelBackColor;
        comboBox.ForeColor = TextColor;
        comboBox.Font = UiFont;
        comboBox.Margin = new Padding(0, 2, 8, 4);
    }

    private static void StyleNumeric(NumericUpDown numeric)
    {
        numeric.BorderStyle = BorderStyle.FixedSingle;
        numeric.BackColor = PanelBackColor;
        numeric.ForeColor = TextColor;
        numeric.Font = UiFont;
        numeric.Margin = new Padding(0, 2, 8, 4);
    }

    private TabPage BuildProfileTab()
    {
        var tab = new TabPage("Hồ sơ") { BackColor = AppBackColor };
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(12),
            BackColor = AppBackColor
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 210));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        _profileTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            MaxLength = 0,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            Font = MonoFont,
            PlaceholderText = "uid|token"
        };
        StyleTextBox(_profileTextBox);
        root.Controls.Add(_profileTextBox, 0, 0);

        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, BackColor = AppBackColor, Padding = new Padding(0, 5, 0, 0) };
        var importButton = CreateButton("Nhập .txt", 110);
        importButton.Click += (_, _) => ImportProfiles();
        var loadButton = CreateButton("Nạp profile", 110);
        loadButton.Click += (_, _) => LoadProfilesFromInput();
        _checkTokensButton = CreateButton("Check token", 120);
        _checkTokensButton.Click += async (_, _) => await CheckTokensAsync();
        var saveDataButton = CreateButton("Lưu dữ liệu", 110);
        saveDataButton.Click += (_, _) => SaveAllSettings(showMessage: true);
        var deleteCheckedButton = CreateButton("Xóa đã tích", 120, DangerColor);
        deleteCheckedButton.Click += (_, _) => DeleteCheckedProfiles();
        var clearButton = CreateButton("Xóa trắng", 100);
        clearButton.Click += (_, _) =>
        {
            _profileTextBox.Clear();
            _profileManager.Clear();
            RefreshProfileGrid();
            SaveAllSettings(showMessage: false);
        };
        buttons.Controls.AddRange([importButton, loadButton, _checkTokensButton, saveDataButton, deleteCheckedButton, clearButton]);
        root.Controls.Add(buttons, 0, 1);

        _profileGrid = CreateGrid();
        _profileGrid.ReadOnly = false;
        _profileGrid.CurrentCellDirtyStateChanged += (_, _) =>
        {
            if (_profileGrid.IsCurrentCellDirty)
            {
                _profileGrid.CommitEdit(DataGridViewDataErrorContexts.Commit);
            }
        };
        _profileGrid.Columns.Add(new DataGridViewCheckBoxColumn
        {
            Name = "Checked",
            HeaderText = "Chọn",
            Width = 50,
            ReadOnly = false,
            SortMode = DataGridViewColumnSortMode.NotSortable
        });
        _profileGrid.Columns.Add("Index", "STT");
        _profileGrid.Columns.Add("Uid", "UID");
        _profileGrid.Columns.Add("Token", "Token");
        _profileGrid.Columns.Add("Status", "Trạng thái token");
        _profileGrid.Columns.Add("Tasks", "Số tác vụ");
        _profileGrid.Columns.Add("Error", "Lỗi gần nhất");
        foreach (DataGridViewColumn column in _profileGrid.Columns)
        {
            if (column.Name != "Checked")
            {
                column.ReadOnly = true;
            }
        }
        SetColumnWidths(_profileGrid, 50, 55, 160, 420, 150, 90, 420);
        root.Controls.Add(_profileGrid, 0, 2);

        tab.Controls.Add(root);
        return tab;
    }

    private TabPage BuildInteractionTab()
    {
        var tab = new TabPage("Tương tác") { BackColor = AppBackColor };
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Padding = new Padding(12),
            BackColor = AppBackColor
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 320));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 264));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var inputGrid = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 2, BackColor = AppBackColor };
        inputGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 26));
        inputGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 54));
        inputGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 20));
        inputGrid.RowStyles.Add(new RowStyle(SizeType.Absolute, 24));
        inputGrid.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _uidCountLabel = CreateCountLabel();
        _linkCountLabel = CreateCountLabel();
        _postCountLabel = CreateCountLabel();
        inputGrid.Controls.Add(CreateHeaderWithCount("UID profile (để trống = tự check bằng Graph):", _uidCountLabel), 0, 0);
        inputGrid.Controls.Add(CreateHeaderWithCount("Link comment:", _linkCountLabel), 1, 0);
        inputGrid.Controls.Add(CreateHeaderWithCount("ID/link bài viết:", _postCountLabel), 2, 0);

        _uidsTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            MaxLength = 0,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            Font = MonoFont,
            PlaceholderText = "Nhập 1 UID áp dụng tất cả, hoặc mỗi dòng 1 UID tương ứng link"
        };
        StyleTextBox(_uidsTextBox);
        _uidsTextBox.TextChanged += (_, _) => UpdateInteractionCounts();
        inputGrid.Controls.Add(_uidsTextBox, 0, 1);

        _linksTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            MaxLength = 0,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            Font = MonoFont,
            PlaceholderText = "Mỗi dòng 1 link comment hoặc comment_id"
        };
        StyleTextBox(_linksTextBox);
        _linksTextBox.TextChanged += (_, _) => UpdateInteractionCounts();
        inputGrid.Controls.Add(_linksTextBox, 1, 1);

        _postIdTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            MaxLength = 0,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            Font = MonoFont,
            PlaceholderText = "Dùng khi Comment mới"
        };
        StyleTextBox(_postIdTextBox);
        _postIdTextBox.TextChanged += (_, _) => UpdateInteractionCounts();
        inputGrid.Controls.Add(_postIdTextBox, 2, 1);
        root.Controls.Add(inputGrid, 0, 0);

        var options = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 6, RowCount = 5, BackColor = AppBackColor };
        options.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        options.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 180));
        options.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        options.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        options.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        options.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        options.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        options.RowStyles.Add(new RowStyle(SizeType.Absolute, 88));
        options.RowStyles.Add(new RowStyle(SizeType.Absolute, 58));
        options.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        options.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));

        options.Controls.Add(CreateLabel("Hành động:"), 0, 0);
        _actionCombo = new ComboBox { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDownList };
        _actionCombo.Items.AddRange(["Chỉnh sửa comment", "Xóa comment", "Comment mới"]);
        _actionCombo.SelectedIndex = 0;
        StyleComboBox(_actionCombo);
        options.Controls.Add(_actionCombo, 1, 0);

        options.Controls.Add(CreateLabel("Số luồng:"), 2, 0);
        _threadsInput = new NumericUpDown { Dock = DockStyle.Left, Minimum = 1, Maximum = 200, Value = 5, Width = 100 };
        StyleNumeric(_threadsInput);
        options.Controls.Add(_threadsInput, 3, 0);

        options.Controls.Add(CreateLabel("Nội dung mới:"), 0, 1);
        _editTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            MaxLength = 0,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            PlaceholderText = "Nhập 1 hoặc nhiều nội dung. Mỗi block cách nhau bằng 1 dòng trống."
        };
        StyleTextBox(_editTextBox);
        options.SetColumnSpan(_editTextBox, 5);
        options.Controls.Add(_editTextBox, 1, 1);

        options.Controls.Add(CreateLabel("File ảnh:"), 0, 2);
        _imageFolderTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            MaxLength = 0,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            PlaceholderText = "Nhập/chọn file ảnh, có thể nhiều dòng"
        };
        StyleTextBox(_imageFolderTextBox);
        options.SetColumnSpan(_imageFolderTextBox, 3);
        options.Controls.Add(_imageFolderTextBox, 1, 2);
        var chooseImageFolderButton = CreateButton("Chọn file", dock: DockStyle.Fill);
        chooseImageFolderButton.Click += (_, _) => ChooseImageFiles();
        options.Controls.Add(chooseImageFolderButton, 4, 2);
        var saveInteractionDataButton = CreateButton("Lưu dữ liệu", dock: DockStyle.Fill);
        saveInteractionDataButton.Click += (_, _) => SaveAllSettings(showMessage: true);
        options.Controls.Add(saveInteractionDataButton, 5, 2);

        options.Controls.Add(CreateLabel("Mỗi UID cmt:"), 0, 3);
        _postsPerUidInput = new NumericUpDown { Dock = DockStyle.Left, Minimum = 1, Maximum = 100000, Value = 1, Width = 100 };
        StyleNumeric(_postsPerUidInput);
        options.Controls.Add(_postsPerUidInput, 1, 3);
        options.Controls.Add(CreateLabel("post"), 2, 3);

        options.Controls.Add(CreateLabel("Delay từ:"), 0, 4);
        _delayMinInput = new NumericUpDown { Dock = DockStyle.Left, Minimum = 0, Maximum = 86400, Value = 0, Width = 100 };
        StyleNumeric(_delayMinInput);
        options.Controls.Add(_delayMinInput, 1, 4);
        options.Controls.Add(CreateLabel("đến:"), 2, 4);
        _delayMaxInput = new NumericUpDown { Dock = DockStyle.Left, Minimum = 0, Maximum = 86400, Value = 0, Width = 100 };
        StyleNumeric(_delayMaxInput);
        options.Controls.Add(_delayMaxInput, 3, 4);
        options.Controls.Add(CreateLabel("sau mỗi vòng:"), 4, 4);
        _delayEveryRoundsInput = new NumericUpDown { Dock = DockStyle.Left, Minimum = 1, Maximum = 100000, Value = 1, Width = 100 };
        StyleNumeric(_delayEveryRoundsInput);
        options.Controls.Add(_delayEveryRoundsInput, 5, 4);

        _startTasksButton = CreateButton("Bắt đầu", backColor: PrimaryColor, dock: DockStyle.Fill);
        _startTasksButton.Click += async (_, _) => await StartTasksAsync();
        _stopTasksButton = CreateButton("Dừng", backColor: DangerColor, dock: DockStyle.Fill);
        _stopTasksButton.Enabled = false;
        _stopTasksButton.Click += (_, _) => StopTasks();
        options.Controls.Add(_startTasksButton, 4, 0);
        options.Controls.Add(_stopTasksButton, 5, 0);
        root.Controls.Add(options, 0, 1);

        _statsLabel = new Label
        {
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            Text = "Tổng: 0 | Đã chạy: 0 | Thành công: 0 | Thất bại: 0 | Đang chờ proxy: 0",
            ForeColor = PrimaryDarkColor,
            Font = UiFontBold,
            BackColor = PrimarySoftColor,
            Padding = new Padding(10, 0, 10, 0)
        };
        root.Controls.Add(_statsLabel, 0, 2);

        _logGrid = CreateGrid();
        _logGrid.Columns.Add("Index", "STT");
        _logGrid.Columns.Add("Uid", "UID");
        _logGrid.Columns.Add("Link", "Link comment");
        _logGrid.Columns.Add("Action", "Hành động");
        _logGrid.Columns.Add("Proxy", "Proxy");
        _logGrid.Columns.Add("Status", "Trạng thái");
        _logGrid.Columns.Add("Error", "Lỗi");
        SetColumnWidths(_logGrid, 55, 160, 760, 90, 180, 120, 560);
        root.Controls.Add(_logGrid, 0, 3);

        tab.Controls.Add(root);
        return tab;
    }

    private TabPage BuildProxyTab()
    {
        var tab = new TabPage("Proxy") { BackColor = AppBackColor };
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(12),
            BackColor = AppBackColor
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 238));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var inputs = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 4, RowCount = 5, BackColor = AppBackColor };
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 160));
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        for (var i = 0; i < 5; i++)
        {
            inputs.RowStyles.Add(new RowStyle(SizeType.Absolute, i == 1 ? 86 : 36));
        }

        inputs.Controls.Add(CreateLabel("Token Kiot:"), 0, 0);
        _kiotAuthTokenTextBox = new TextBox { Dock = DockStyle.Fill, UseSystemPasswordChar = true };
        StyleTextBox(_kiotAuthTokenTextBox);
        inputs.Controls.Add(_kiotAuthTokenTextBox, 1, 0);

        inputs.Controls.Add(CreateLabel("Lượt mỗi IP:"), 2, 0);
        _usesPerProxyInput = new NumericUpDown { Dock = DockStyle.Left, Minimum = 1, Maximum = 100, Value = 4, Width = 90 };
        StyleNumeric(_usesPerProxyInput);
        inputs.Controls.Add(_usesPerProxyInput, 3, 0);

        inputs.Controls.Add(CreateLabel("API key proxy:"), 0, 1);
        _proxyKeysTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            MaxLength = 0,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            Font = MonoFont,
            PlaceholderText = "Mỗi dòng 1 API key get IP"
        };
        StyleTextBox(_proxyKeysTextBox);
        inputs.SetColumnSpan(_proxyKeysTextBox, 3);
        inputs.Controls.Add(_proxyKeysTextBox, 1, 1);

        inputs.Controls.Add(CreateLabel("URL lấy IP mới:"), 0, 2);
        _getNewProxyUrlTextBox = new TextBox { Dock = DockStyle.Fill };
        StyleTextBox(_getNewProxyUrlTextBox);
        inputs.SetColumnSpan(_getNewProxyUrlTextBox, 3);
        inputs.Controls.Add(_getNewProxyUrlTextBox, 1, 2);

        inputs.Controls.Add(CreateLabel("URL IP hiện tại:"), 0, 3);
        _getCurrentProxyUrlTextBox = new TextBox { Dock = DockStyle.Fill };
        StyleTextBox(_getCurrentProxyUrlTextBox);
        inputs.SetColumnSpan(_getCurrentProxyUrlTextBox, 3);
        inputs.Controls.Add(_getCurrentProxyUrlTextBox, 1, 3);

        var hint = new Label
        {
            Text = "Dùng placeholder {apiKey}. Dữ liệu nhạy cảm được lưu bằng Windows DPAPI theo user hiện tại.",
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            ForeColor = Color.FromArgb(75, 85, 99),
            BackColor = AppBackColor
        };
        inputs.SetColumnSpan(hint, 4);
        inputs.Controls.Add(hint, 0, 4);
        root.Controls.Add(inputs, 0, 0);

        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, BackColor = AppBackColor, Padding = new Padding(0, 5, 0, 0) };
        var saveButton = CreateButton("Lưu cấu hình", 130);
        saveButton.Click += (_, _) => SaveAllSettings(showMessage: true);
        _startProxyButton = CreateButton("Bắt đầu proxy", 130, PrimaryColor);
        _startProxyButton.Click += (_, _) =>
        {
            SaveAllSettings(showMessage: false);
            _proxyManager.Configure(_settings);
            _proxyManager.Start();
            UpdateProxyButtons();
        };
        _stopProxyButton = CreateButton("Dừng proxy", 120, DangerColor);
        _stopProxyButton.Click += (_, _) =>
        {
            _proxyManager.Stop();
            UpdateProxyButtons();
        };
        var clearSavedButton = CreateButton("Xóa cấu hình lưu", 150);
        clearSavedButton.Click += (_, _) =>
        {
            _settingsStore.Clear();
            MessageBox.Show("Đã xóa cấu hình đã lưu.", "Proxy", MessageBoxButtons.OK, MessageBoxIcon.Information);
        };
        buttons.Controls.AddRange([saveButton, _startProxyButton, _stopProxyButton, clearSavedButton]);
        root.Controls.Add(buttons, 0, 1);

        _proxyGrid = CreateGrid();
        _proxyGrid.Columns.Add("Index", "STT");
        _proxyGrid.Columns.Add("Key", "API key ẩn");
        _proxyGrid.Columns.Add("Proxy", "Proxy hiện tại");
        _proxyGrid.Columns.Add("Remaining", "Lượt còn lại");
        _proxyGrid.Columns.Add("Reserved", "Đang giữ");
        _proxyGrid.Columns.Add("Status", "Trạng thái");
        _proxyGrid.Columns.Add("LastGet", "Lần lấy IP gần nhất");
        _proxyGrid.Columns.Add("Error", "Lỗi gần nhất");
        SetColumnWidths(_proxyGrid, 55, 180, 220, 100, 90, 120, 170, 420);
        root.Controls.Add(_proxyGrid, 0, 2);
        UpdateProxyButtons();

        tab.Controls.Add(root);
        return tab;
    }

    private void WireEvents()
    {
        _proxyManager.StateChanged += () => Ui(() =>
        {
            RefreshProxyGrid();
            UpdateProxyButtons();
        });
        _taskManager.LogAdded += entry => Ui(() => AddLog(entry));
        _taskManager.StatsChanged += stats => Ui(() => UpdateStats(stats));
        _taskManager.ProfileStatusChanged += (uid, status, error) => Ui(() => UpdateProfileStatusRow(uid, status, error));
    }

    private void UpdateProxyButtons()
    {
        if (_startProxyButton is null || _stopProxyButton is null)
        {
            return;
        }

        SetButtonRunning(_startProxyButton, _proxyManager.IsStarted);
        _stopProxyButton.Enabled = _proxyManager.IsStarted;
    }

    private void LoadSettingsIntoUi()
    {
        _profileTextBox.Text = _settings.ProfileText;
        if (!string.IsNullOrWhiteSpace(_profileTextBox.Text))
        {
            _profileManager.LoadFromText(_profileTextBox.Text);
            _profileManager.ApplyStates(_settings.ProfileStates);
            RefreshProfileGrid();
        }

        _uidsTextBox.Text = _settings.InteractionUidText;
        _linksTextBox.Text = _settings.InteractionLinkText;
        _postIdTextBox.Text = _settings.InteractionPostIdText;
        _actionCombo.SelectedIndex = Math.Clamp(_settings.InteractionActionIndex, 0, Math.Max(0, _actionCombo.Items.Count - 1));
        _threadsInput.Value = Math.Clamp(_settings.InteractionThreads, (int)_threadsInput.Minimum, (int)_threadsInput.Maximum);
        _delayMinInput.Value = Math.Clamp(_settings.InteractionDelayMinSeconds, (int)_delayMinInput.Minimum, (int)_delayMinInput.Maximum);
        _delayMaxInput.Value = Math.Clamp(_settings.InteractionDelayMaxSeconds, (int)_delayMaxInput.Minimum, (int)_delayMaxInput.Maximum);
        _delayEveryRoundsInput.Value = Math.Clamp(_settings.InteractionDelayEveryRounds <= 0 ? 1 : _settings.InteractionDelayEveryRounds, (int)_delayEveryRoundsInput.Minimum, (int)_delayEveryRoundsInput.Maximum);
        _postsPerUidInput.Value = Math.Clamp(_settings.InteractionPostsPerUid <= 0 ? 1 : _settings.InteractionPostsPerUid, (int)_postsPerUidInput.Minimum, (int)_postsPerUidInput.Maximum);
        _editTextBox.Text = _settings.InteractionEditText;
        _imageFolderTextBox.Text = _settings.InteractionImageFolder;
        _kiotAuthTokenTextBox.Text = _settings.KiotAuthToken;
        _proxyKeysTextBox.Text = _settings.ProxyApiKeysText;
        _getNewProxyUrlTextBox.Text = _settings.GetNewProxyUrlTemplate;
        _getCurrentProxyUrlTextBox.Text = _settings.GetCurrentProxyUrlTemplate;
        _usesPerProxyInput.Value = Math.Clamp(_settings.UsesPerProxy, 1, 100);
        UpdateInteractionCounts();
    }

    private void SaveAllSettings(bool showMessage)
    {
        _settings = new AppSettings
        {
            ProfileText = _profileTextBox.Text,
            ProfileStates = _profileManager.ExportStates(),
            InteractionUidText = _uidsTextBox.Text,
            InteractionLinkText = _linksTextBox.Text,
            InteractionPostIdText = _postIdTextBox.Text,
            InteractionActionIndex = _actionCombo.SelectedIndex,
            InteractionThreads = (int)_threadsInput.Value,
            InteractionDelayMinSeconds = (int)_delayMinInput.Value,
            InteractionDelayMaxSeconds = (int)_delayMaxInput.Value,
            InteractionDelayEveryRounds = (int)_delayEveryRoundsInput.Value,
            InteractionPostsPerUid = (int)_postsPerUidInput.Value,
            InteractionEditText = _editTextBox.Text,
            InteractionImageFolder = _imageFolderTextBox.Text,
            KiotAuthToken = _kiotAuthTokenTextBox.Text.Trim(),
            ProxyApiKeysText = _proxyKeysTextBox.Text.Trim(),
            GetNewProxyUrlTemplate = string.IsNullOrWhiteSpace(_getNewProxyUrlTextBox.Text)
                ? new AppSettings().GetNewProxyUrlTemplate
                : _getNewProxyUrlTextBox.Text.Trim(),
            GetCurrentProxyUrlTemplate = string.IsNullOrWhiteSpace(_getCurrentProxyUrlTextBox.Text)
                ? new AppSettings().GetCurrentProxyUrlTemplate
                : _getCurrentProxyUrlTextBox.Text.Trim(),
            UsesPerProxy = (int)_usesPerProxyInput.Value
        };
        _settingsStore.Save(_settings);

        if (showMessage)
        {
            MessageBox.Show("Đã lưu dữ liệu vào máy.", "Lưu dữ liệu", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }

    private void ImportProfiles()
    {
        using var dialog = new OpenFileDialog
        {
            Filter = "Text files (*.txt)|*.txt|All files (*.*)|*.*",
            Title = "Chọn file uid|token"
        };

        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            _profileTextBox.Text = File.ReadAllText(dialog.FileName);
            LoadProfilesFromInput();
        }
    }

    private void LoadProfilesFromInput()
    {
        var result = _profileManager.MergeFromText(_profileTextBox.Text);
        _profileManager.ApplyStates(_settings.ProfileStates);
        _profileTextBox.Text = _profileManager.ExportText();
        RefreshProfileGrid();
        SaveAllSettings(showMessage: false);
        if (result.Errors.Count > 0)
        {
            MessageBox.Show(string.Join(Environment.NewLine, result.Errors.Take(20)), "Lỗi profile", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        else if (result.DuplicateCount > 0)
        {
            MessageBox.Show($"Đã thêm {result.AddedCount} UID mới, refresh token cho {result.DuplicateCount} UID trùng.", "Profile", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }

    private void ChooseImageFiles()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Chọn file ảnh",
            Filter = "Image files|*.jpg;*.jpeg;*.jfif;*.pjpeg;*.pjp;*.png;*.gif;*.webp;*.bmp;*.dib;*.tif;*.tiff;*.heic;*.heif;*.avif;*.ico;*.svg|All files|*.*",
            Multiselect = true,
            CheckFileExists = true
        };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            _imageFolderTextBox.Text = string.Join(Environment.NewLine, dialog.FileNames);
            SaveAllSettings(showMessage: false);
            var imageCount = CommentTaskManager.LoadImages(_imageFolderTextBox.Text).Count;
            MessageBox.Show(
                imageCount > 0
                    ? $"Đã chọn {imageCount} file ảnh."
                    : "Không đọc được file ảnh nào. Kiểm tra lại định dạng file ảnh.",
                "File ảnh",
                MessageBoxButtons.OK,
                imageCount > 0 ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
        }
    }

    private async Task CheckTokensAsync()
    {
        if (_profileManager.Profiles.Count == 0)
        {
            LoadProfilesFromInput();
        }

        if (_profileManager.Profiles.Count == 0)
        {
            MessageBox.Show("Chưa có profile hợp lệ.", "Check token", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        SetButtonRunning(_checkTokensButton, true);
        try
        {
            using var httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(20) };
            using var semaphore = new SemaphoreSlim(10);
            var profiles = _profileManager.Profiles.ToList();
            var tasks = profiles.Select(async profile =>
            {
                await semaphore.WaitAsync();
                try
                {
                    var result = await CheckOneTokenAsync(httpClient, profile);
                    Ui(() =>
                    {
                        profile.TokenStatus = result.Status;
                        profile.LastError = result.Error;
                        UpdateProfileStatusRow(profile.Uid, profile.TokenStatus, profile.LastError);
                    });
                }
                finally
                {
                    semaphore.Release();
                }
            });

            await Task.WhenAll(tasks);
            SaveAllSettings(showMessage: false);
            MessageBox.Show("Đã check xong token.", "Check token", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        finally
        {
            SetButtonRunning(_checkTokensButton, false);
        }
    }

    private static async Task<TokenCheckResult> CheckOneTokenAsync(HttpClient httpClient, ProfileAccount profile)
    {
        try
        {
            var url = $"https://graph.facebook.com/me?fields=id&access_token={Uri.EscapeDataString(profile.Token)}";
            using var response = await httpClient.GetAsync(url);
            var body = await response.Content.ReadAsStringAsync();
            if (response.IsSuccessStatusCode)
            {
                var graphUid = ExtractGraphUid(body);
                if (!string.IsNullOrWhiteSpace(graphUid) &&
                    !string.Equals(graphUid, profile.Uid, StringComparison.OrdinalIgnoreCase))
                {
                    return new TokenCheckResult("Live", $"Token live nhưng UID token là {graphUid}, khác UID profile {profile.Uid}.");
                }

                return new TokenCheckResult("Live", "");
            }

            return ParseTokenCheckError((int)response.StatusCode, body);
        }
        catch (Exception ex)
        {
            return new TokenCheckResult("Die", ex.Message);
        }
    }

    private static string ExtractGraphUid(string body)
    {
        try
        {
            using var document = System.Text.Json.JsonDocument.Parse(body);
            return document.RootElement.TryGetProperty("id", out var id) ? id.ToString() : "";
        }
        catch
        {
            return "";
        }
    }

    private static TokenCheckResult ParseTokenCheckError(int httpStatus, string body)
    {
        try
        {
            using var document = System.Text.Json.JsonDocument.Parse(body);
            if (document.RootElement.TryGetProperty("error", out var error))
            {
                var message = GetJsonString(error, "message");
                var code = GetJsonInt(error, "code");
                var subcode = GetJsonInt(error, "error_subcode");
                var issueCode = subcode != 0 ? subcode : code;
                var fullMessage = $"Graph API {httpStatus}: {message} (code {code}, subcode {subcode}).";
                var text = message.ToLowerInvariant();

                if (code == 190 || subcode is 458 or 460 or 463 or 467 || text.Contains("access token") || text.Contains("oauth"))
                {
                    return new TokenCheckResult(issueCode != 0 ? $"Token out {issueCode}" : "Token out", fullMessage);
                }

                if (code is 282 or 459 or 490 or 492 or 493 or 494 or 959 ||
                    subcode is 282 or 459 or 490 or 492 or 493 or 494 or 959 ||
                    text.Contains("checkpoint") ||
                    text.Contains("security check"))
                {
                    return new TokenCheckResult(issueCode != 0 ? $"Checkpoint {issueCode}" : "Checkpoint", fullMessage);
                }

                return new TokenCheckResult(issueCode != 0 ? $"Die {issueCode}" : "Die", fullMessage);
            }
        }
        catch
        {
        }

        return new TokenCheckResult("Die", $"Graph API {httpStatus}: {body}");
    }

    private static string GetJsonString(System.Text.Json.JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind != System.Text.Json.JsonValueKind.Null
            ? value.ToString()
            : "";
    }

    private static int GetJsonInt(System.Text.Json.JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return 0;
        }

        return value.ValueKind switch
        {
            System.Text.Json.JsonValueKind.Number when value.TryGetInt32(out var number) => number,
            System.Text.Json.JsonValueKind.String when int.TryParse(value.GetString(), out var number) => number,
            _ => 0
        };
    }

    private async Task StartTasksAsync()
    {
        if (_profileManager.Profiles.Count == 0)
        {
            LoadProfilesFromInput();
        }

        SaveAllSettings(showMessage: false);

        if (_profileManager.Profiles.Count == 0)
        {
            MessageBox.Show("Chưa có profile hợp lệ.", "Tương tác", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        var uids = ReadNonEmptyLines(_uidsTextBox.Text);
        var action = _actionCombo.SelectedIndex switch
        {
            1 => CommentActionKind.Delete,
            2 => CommentActionKind.NewComment,
            _ => CommentActionKind.Edit
        };

        if (action is CommentActionKind.Edit or CommentActionKind.NewComment && string.IsNullOrWhiteSpace(_editTextBox.Text))
        {
            MessageBox.Show("Chưa nhập nội dung.", "Tương tác", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        if (action is CommentActionKind.Edit or CommentActionKind.NewComment && !string.IsNullOrWhiteSpace(_imageFolderTextBox.Text))
        {
            var imageCount = CommentTaskManager.LoadImages(_imageFolderTextBox.Text).Count;
            if (imageCount == 0)
            {
                MessageBox.Show(
                    "Ô ảnh có nhập đường dẫn nhưng tool không đọc được file ảnh nào. Kiểm tra lại file ảnh rồi bấm Bắt đầu lại.",
                    "Ảnh",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
                return;
            }
        }

        List<CommentTaskInput> tasks;
        if (action == CommentActionKind.NewComment)
        {
            var posts = ReadNonEmptyLines(_postIdTextBox.Text)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();
            if (posts.Count == 0)
            {
                MessageBox.Show("Chưa nhập ID/link bài viết để comment mới.", "Tương tác", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            var targetUids = (uids.Count == 0 ? _profileManager.Profiles.Select(profile => profile.Uid) : uids)
                .Where(uid => !string.IsNullOrWhiteSpace(uid))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();
            if (targetUids.Count == 0)
            {
                MessageBox.Show("Chưa có UID/profile để comment mới.", "Tương tác", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            tasks = BuildNewCommentTasks(targetUids, posts, (int)_postsPerUidInput.Value);
            if (tasks.Count == 0)
            {
                MessageBox.Show("Không tạo được task comment mới từ UID/post đã nhập.", "Tương tác", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
        }
        else
        {
            var links = ReadNonEmptyLines(_linksTextBox.Text);
            if (links.Count == 0)
            {
                MessageBox.Show("Chưa nhập link comment.", "Tương tác", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            if (uids.Count > 1 && uids.Count != links.Count)
            {
                MessageBox.Show("Nếu nhập nhiều UID thì số dòng UID phải bằng số dòng link. Có thể để trống UID để Graph tự check.", "Tương tác", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            tasks = links
                .Select((link, index) =>
                {
                    var manualUid = uids.Count == 0 ? "" : uids.Count == 1 ? uids[0] : uids[index];
                    return new CommentTaskInput(manualUid, link);
                })
                .ToList();
        }

        _logGrid.Rows.Clear();
        _logRowsByKey.Clear();
        _tasksStoppedByUser = false;
        SetButtonRunning(_startTasksButton, true);
        _stopTasksButton.Enabled = true;

        try
        {
            await _taskManager.StartAsync(
                tasks,
                action,
                (int)_threadsInput.Value,
                new DelaySettings((int)_delayMinInput.Value, (int)_delayMaxInput.Value, (int)_delayEveryRoundsInput.Value),
                _editTextBox.Text,
                _imageFolderTextBox.Text);
        }
        catch (OperationCanceledException)
        {
        }
        catch (IOException ex) when (ex.Message.Contains("aborted", StringComparison.OrdinalIgnoreCase))
        {
        }
        finally
        {
            SetButtonRunning(_startTasksButton, false);
            _stopTasksButton.Enabled = false;
            RefreshProfileGrid();
            if (!_tasksStoppedByUser)
            {
                ShowTaskFinishedPopup();
            }
        }
    }

    private static List<string> ReadNonEmptyLines(string text)
    {
        return text
            .Replace("\r\n", "\n")
            .Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToList();
    }

    private void UpdateInteractionCounts()
    {
        if (_uidCountLabel is null || _linkCountLabel is null || _postCountLabel is null)
        {
            return;
        }

        _uidCountLabel.Text = CountNonEmptyLines(_uidsTextBox.Text).ToString();
        _linkCountLabel.Text = CountNonEmptyLines(_linksTextBox.Text).ToString();
        _postCountLabel.Text = CountNonEmptyLines(_postIdTextBox.Text).ToString();
    }

    private static int CountNonEmptyLines(string text)
    {
        return text
            .Replace("\r\n", "\n")
            .Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Length;
    }

    private static List<CommentTaskInput> BuildNewCommentTasks(IReadOnlyList<string> uids, IReadOnlyList<string> posts, int postsPerUid)
    {
        var tasks = new List<CommentTaskInput>();
        var uidCounts = uids.ToDictionary(uid => uid, _ => 0, StringComparer.OrdinalIgnoreCase);
        var postIndex = 0;

        while (postIndex < posts.Count && uidCounts.Values.Any(count => count < postsPerUid))
        {
            foreach (var uid in uids)
            {
                if (postIndex >= posts.Count)
                {
                    break;
                }

                if (uidCounts[uid] >= postsPerUid)
                {
                    continue;
                }

                tasks.Add(new CommentTaskInput(uid, posts[postIndex]));
                uidCounts[uid]++;
                postIndex++;
            }
        }

        return tasks;
    }

    private void StopTasks()
    {
        _tasksStoppedByUser = true;
        _taskManager.Stop();
        _stopTasksButton.Enabled = false;
    }

    private void ShowTaskFinishedPopup()
    {
        var stats = _taskManager.Stats;
        MessageBox.Show(
            $"Đã chạy xong.\n\nTổng: {stats.Total}\nĐã chạy: {stats.Processed}\nThành công: {stats.Success}\nThất bại: {stats.Failed}",
            "Hoàn tất",
            MessageBoxButtons.OK,
            stats.Failed > 0 ? MessageBoxIcon.Warning : MessageBoxIcon.Information);
    }

    private void DeleteCheckedProfiles()
    {
        _profileGrid.EndEdit();

        var checkedUids = _profileGrid.Rows
            .Cast<DataGridViewRow>()
            .Where(row => Convert.ToBoolean(row.Cells["Checked"].Value ?? false))
            .Select(row => row.Cells["Uid"].Value?.ToString() ?? "")
            .Where(uid => !string.IsNullOrWhiteSpace(uid))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (checkedUids.Count == 0)
        {
            MessageBox.Show("Chưa tích profile nào để xóa.", "Xóa profile", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        var confirm = MessageBox.Show(
            $"Bạn muốn xóa {checkedUids.Count} profile đã tích?",
            "Xác nhận xóa",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning);
        if (confirm != DialogResult.Yes)
        {
            return;
        }

        var removed = _profileManager.RemoveByUids(checkedUids);
        _profileTextBox.Text = _profileManager.ExportText();
        RefreshProfileGrid();
        SaveAllSettings(showMessage: false);
        MessageBox.Show($"Đã xóa {removed} profile.", "Xóa profile", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private void RefreshProfileGrid()
    {
        _profileGrid.Rows.Clear();
        foreach (var profile in _profileManager.Profiles)
        {
            var rowIndex = _profileGrid.Rows.Add(
                false,
                profile.Index,
                profile.Uid,
                profile.Token,
                profile.TokenStatus,
                profile.TaskCount,
                profile.LastError);
            ApplyProfileRowStyle(_profileGrid.Rows[rowIndex], profile.TokenStatus);
        }
    }

    private void UpdateProfileStatusRow(string uid, string status, string error)
    {
        foreach (DataGridViewRow row in _profileGrid.Rows)
        {
            if (!string.Equals(row.Cells["Uid"].Value?.ToString(), uid, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            row.Cells["Status"].Value = status;
            row.Cells["Error"].Value = error;
            ApplyProfileRowStyle(row, status);
            SaveAllSettings(showMessage: false);
            return;
        }
    }

    private static void ApplyProfileRowStyle(DataGridViewRow row, string status)
    {
        var statusColor = GetProfileStatusColor(status);
        var backgroundColor = GetProfileStatusBackColor(status);
        row.DefaultCellStyle.BackColor = backgroundColor;
        row.DefaultCellStyle.SelectionBackColor = ControlPaint.Dark(backgroundColor);
        row.Cells["Status"].Style.ForeColor = statusColor;
        row.Cells["Status"].Style.Font = UiFontBold;
        row.Cells["Error"].Style.ForeColor = statusColor;
    }

    private static Color GetProfileStatusColor(string status)
    {
        if (status.Contains("Token out", StringComparison.OrdinalIgnoreCase))
        {
            return WarningColor;
        }

        if (status.Contains("Live", StringComparison.OrdinalIgnoreCase))
        {
            return SuccessColor;
        }

        if (status.Contains("Die", StringComparison.OrdinalIgnoreCase) ||
            status.Contains("Checkpoint", StringComparison.OrdinalIgnoreCase))
        {
            return DangerColor;
        }

        return TextColor;
    }

    private static Color GetProfileStatusBackColor(string status)
    {
        if (status.Contains("Token out", StringComparison.OrdinalIgnoreCase))
        {
            return Color.FromArgb(254, 243, 199);
        }

        if (status.Contains("Live", StringComparison.OrdinalIgnoreCase))
        {
            return Color.FromArgb(220, 252, 231);
        }

        if (status.Contains("Die", StringComparison.OrdinalIgnoreCase) ||
            status.Contains("Checkpoint", StringComparison.OrdinalIgnoreCase))
        {
            return Color.FromArgb(254, 226, 226);
        }

        return PanelBackColor;
    }

    private void RefreshProxyGrid()
    {
        if (_proxyGrid is null)
        {
            return;
        }

        _proxyGrid.Rows.Clear();
        foreach (var proxy in _proxyManager.Snapshot())
        {
            _proxyGrid.Rows.Add(
                proxy.Index,
                proxy.MaskedApiKey,
                proxy.CurrentProxy,
                proxy.RemainingUses,
                proxy.ReservedUses,
                proxy.Status,
                proxy.LastGetIpAt?.ToString("yyyy-MM-dd HH:mm:ss") ?? "",
                proxy.LastError);
        }
    }

    private void AddLog(TaskLogEntry entry)
    {
        DataGridViewRow? row = null;
        if (!string.IsNullOrWhiteSpace(entry.Key))
        {
            _logRowsByKey.TryGetValue(entry.Key, out row);
        }

        if (row is null)
        {
            var rowIndex = _logGrid.Rows.Add(
                _logGrid.Rows.Count + 1,
                entry.Uid,
                entry.CommentLink,
                entry.Action,
                entry.Proxy,
                entry.Status,
                entry.Error);
            row = _logGrid.Rows[rowIndex];
            row.Tag = entry.Key;
            if (!string.IsNullOrWhiteSpace(entry.Key))
            {
                _logRowsByKey[entry.Key] = row;
            }
        }
        else
        {
            row.Cells["Uid"].Value = entry.Uid;
            if (!string.IsNullOrWhiteSpace(entry.CommentLink))
            {
                row.Cells["Link"].Value = entry.CommentLink;
            }

            row.Cells["Action"].Value = entry.Action;
            row.Cells["Proxy"].Value = entry.Proxy;
            row.Cells["Status"].Value = entry.Status;
            row.Cells["Error"].Value = entry.Error;
        }

        ApplyLogRowStyle(row);

        if (_logGrid.Rows.Count > 0)
        {
            _logGrid.FirstDisplayedScrollingRowIndex = Math.Max(0, row.Index);
        }
    }

    private static void ApplyLogRowStyle(DataGridViewRow row)
    {
        var status = row.Cells["Status"].Value?.ToString() ?? "";
        var color = status switch
        {
            var value when value.Contains("Thanh cong", StringComparison.OrdinalIgnoreCase) => SuccessColor,
            var value when value.Contains("That bai", StringComparison.OrdinalIgnoreCase) => DangerColor,
            var value when value.Contains("Token out", StringComparison.OrdinalIgnoreCase) => WarningColor,
            var value when value.Contains("Die", StringComparison.OrdinalIgnoreCase) => DangerColor,
            var value when value.Contains("Checkpoint", StringComparison.OrdinalIgnoreCase) => DangerColor,
            var value when value.Contains("Dang cho proxy", StringComparison.OrdinalIgnoreCase) => WarningColor,
            var value when value.Contains("Dang chay", StringComparison.OrdinalIgnoreCase) => PrimaryDarkColor,
            var value when value.Contains("Cho chay", StringComparison.OrdinalIgnoreCase) => Color.FromArgb(75, 85, 99),
            _ => TextColor
        };

        row.DefaultCellStyle.ForeColor = TextColor;
        row.Cells["Status"].Style.ForeColor = color;
        row.Cells["Status"].Style.Font = UiFontBold;
    }

    private void UpdateStats(TaskStats stats)
    {
        _statsLabel.Text =
            $"Tổng: {stats.Total} | Đã chạy: {stats.Processed} | Thành công: {stats.Success} | Thất bại: {stats.Failed} | Đang chờ proxy: {stats.WaitingProxy}";
    }

    private static DataGridView CreateGrid()
    {
        var grid = new DataGridView
        {
            Dock = DockStyle.Fill,
            AllowUserToAddRows = false,
            AllowUserToDeleteRows = false,
            ReadOnly = true,
            AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.None,
            AutoSizeRowsMode = DataGridViewAutoSizeRowsMode.None,
            SelectionMode = DataGridViewSelectionMode.CellSelect,
            MultiSelect = true,
            RowHeadersVisible = false,
            ScrollBars = ScrollBars.Both,
            ClipboardCopyMode = DataGridViewClipboardCopyMode.EnableWithoutHeaderText,
            BackgroundColor = PanelBackColor,
            BorderStyle = BorderStyle.FixedSingle,
            GridColor = BorderColor,
            CellBorderStyle = DataGridViewCellBorderStyle.SingleHorizontal,
            ColumnHeadersBorderStyle = DataGridViewHeaderBorderStyle.Single,
            EnableHeadersVisualStyles = false,
            RowHeadersWidthSizeMode = DataGridViewRowHeadersWidthSizeMode.DisableResizing
        };
        EnableGridDoubleBuffer(grid);
        grid.DefaultCellStyle.WrapMode = DataGridViewTriState.False;
        grid.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleLeft;
        grid.DefaultCellStyle.BackColor = PanelBackColor;
        grid.DefaultCellStyle.ForeColor = TextColor;
        grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(165, 243, 252);
        grid.DefaultCellStyle.SelectionForeColor = Color.FromArgb(21, 94, 117);
        grid.DefaultCellStyle.Font = UiFont;
        grid.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(248, 250, 252);
        grid.ColumnHeadersDefaultCellStyle.BackColor = PrimaryDarkColor;
        grid.ColumnHeadersDefaultCellStyle.ForeColor = Color.White;
        grid.ColumnHeadersDefaultCellStyle.Font = UiFontBold;
        grid.ColumnHeadersDefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleLeft;
        grid.ColumnHeadersDefaultCellStyle.WrapMode = DataGridViewTriState.False;
        grid.RowTemplate.Height = 26;
        grid.ColumnHeadersHeight = 30;
        grid.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.DisableResizing;
        grid.KeyDown += (_, e) =>
        {
            if (e.Control && e.KeyCode == Keys.C)
            {
                CopySelectedCells(grid);
                e.Handled = true;
            }
        };

        return grid;
    }

    private static void EnableGridDoubleBuffer(DataGridView grid)
    {
        try
        {
            typeof(DataGridView)
                .GetProperty("DoubleBuffered", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
                ?.SetValue(grid, true);
        }
        catch
        {
        }
    }

    private static void CopySelectedCells(DataGridView grid)
    {
        if (grid.SelectedCells.Count == 0)
        {
            return;
        }

        var cells = grid.SelectedCells
            .Cast<DataGridViewCell>()
            .Where(cell => cell.RowIndex >= 0 && cell.ColumnIndex >= 0)
            .OrderBy(cell => cell.RowIndex)
            .ThenBy(cell => cell.ColumnIndex)
            .ToList();

        var lines = cells
            .GroupBy(cell => cell.RowIndex)
            .Select(row => string.Join("\t", row.Select(cell => cell.Value?.ToString() ?? "")));

        Clipboard.SetText(string.Join(Environment.NewLine, lines));
    }

    private static void SetColumnWidths(DataGridView grid, params int[] widths)
    {
        for (var i = 0; i < widths.Length && i < grid.Columns.Count; i++)
        {
            grid.Columns[i].Width = widths[i];
        }
    }

    private void Ui(Action action)
    {
        if (IsDisposed)
        {
            return;
        }

        if (InvokeRequired)
        {
            BeginInvoke(action);
        }
        else
        {
            action();
        }
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        var confirmMessage = _taskManager.IsRunning || _proxyManager.IsStarted
            ? "Tool đang có tác vụ hoặc proxy đang chạy. Bạn có chắc muốn thoát? Tác vụ hiện tại sẽ bị dừng."
            : "Bạn có chắc muốn thoát ứng dụng?";
        var confirm = MessageBox.Show(
            confirmMessage,
            "Xác nhận thoát",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question);
        if (confirm != DialogResult.Yes)
        {
            e.Cancel = true;
            return;
        }

        SaveAllSettings(showMessage: false);
        _taskManager.Stop();
        _proxyManager.Stop();
        base.OnFormClosing(e);
    }
}

public sealed record TokenCheckResult(string Status, string Error);
