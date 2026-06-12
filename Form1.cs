namespace ToolEditDeleteCmt;

public partial class Form1 : Form
{
    private const string AppDisplayName = "FlowMeta";
    private const string DefaultLicenseExpiryText = "Chưa kích hoạt";

    private static readonly Color AppBackColor = Color.FromArgb(232, 241, 255);
    private static readonly Color PanelBackColor = Color.White;
    private static readonly Color BorderColor = Color.FromArgb(147, 197, 253);
    private static readonly Color PrimaryColor = Color.FromArgb(8, 102, 255);
    private static readonly Color PrimaryDarkColor = Color.FromArgb(5, 80, 200);
    private static readonly Color PrimarySoftColor = Color.FromArgb(219, 234, 254);
    private static readonly Color TabBackColor = Color.FromArgb(246, 246, 246);
    private static readonly Color TabSelectedColor = AppBackColor;
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
    private readonly LicenseManager _licenseManager;
    private readonly GitHubUpdateChecker _updateChecker = new();
    private readonly CommentTaskManager _taskManager;
    private readonly Dictionary<string, DataGridViewRow> _logRowsByKey = new(StringComparer.OrdinalIgnoreCase);
    private AppSettings _settings;
    private bool _tasksStoppedByUser;
    private string _logSortColumnName = "Index";
    private SortOrder _logSortDirection = SortOrder.Ascending;

    private TextBox _profileTextBox = null!;
    private DataGridView _profileGrid = null!;
    private Button _checkTokensButton = null!;
    private TabControl _interactionActionTabs = null!;
    private TextBox _editUidTextBox = null!;
    private TextBox _editLinksTextBox = null!;
    private TextBox _deleteUidTextBox = null!;
    private TextBox _deleteLinksTextBox = null!;
    private TextBox _commentUidTextBox = null!;
    private TextBox _commentPostIdTextBox = null!;
    private Label _editUidCountLabel = null!;
    private Label _editLinkCountLabel = null!;
    private Label _deleteUidCountLabel = null!;
    private Label _deleteLinkCountLabel = null!;
    private Label _commentUidCountLabel = null!;
    private Label _commentPostCountLabel = null!;
    private NumericUpDown _threadsInput = null!;
    private NumericUpDown _delayMinInput = null!;
    private NumericUpDown _delayMaxInput = null!;
    private NumericUpDown _delayEveryRoundsInput = null!;
    private NumericUpDown _postsPerUidInput = null!;
    private TextBox _editTextBox = null!;
    private Button _toggleContentButton = null!;
    private RowStyle _contentRowStyle = null!;
    private bool _contentInputVisible = true;
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
    private NumericUpDown _proxyCheckIntervalInput = null!;
    private DataGridView _proxyGrid = null!;
    private System.Windows.Forms.Timer _proxyCountdownTimer = null!;
    private bool _skipExitConfirm;

    public Form1(LicenseManager licenseManager)
    {
        _licenseManager = licenseManager;
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
        Text = BuildWindowTitle();
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
        StyleTabControl(tabs);
        tabs.TabPages.Add(BuildProfileTab());
        tabs.TabPages.Add(BuildInteractionTab());
        tabs.TabPages.Add(BuildProxyTab());
        Controls.Add(tabs);
    }

    private string BuildWindowTitle()
    {
        var status = _licenseManager.GetCurrentStatus();
        if (!status.IsValid || status.ExpiresAtUtc is null)
        {
            return $"{AppDisplayName} - Hạn sử dụng: {DefaultLicenseExpiryText}";
        }

        var expiry = status.ExpiresAtUtc.Value.ToLocalTime();
        var remaining = expiry - DateTimeOffset.Now;
        var remainingDays = Math.Max(0, (int)Math.Ceiling(remaining.TotalDays));
        return $"{AppDisplayName} - Hạn sử dụng đến {expiry:dd/MM/yyyy} - còn {remainingDays} ngày";
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
            BackColor = Color.Transparent,
            Font = UiFontBold
        };
    }

    private static void StyleTabControl(TabControl tabControl)
    {
        tabControl.DrawMode = TabDrawMode.OwnerDrawFixed;
        tabControl.SizeMode = TabSizeMode.Normal;
        tabControl.DrawItem += (_, e) =>
        {
            var selected = e.Index == tabControl.SelectedIndex;
            var tabPage = tabControl.TabPages[e.Index];
            var bounds = e.Bounds;
            var fill = selected ? TabSelectedColor : TabBackColor;
            var textColor = selected ? PrimaryDarkColor : TextColor;

            using var backBrush = new SolidBrush(fill);
            using var borderPen = new Pen(BorderColor);
            e.Graphics.FillRectangle(backBrush, bounds);
            e.Graphics.DrawRectangle(borderPen, bounds.X, bounds.Y, bounds.Width - 1, bounds.Height - 1);

            TextRenderer.DrawText(
                e.Graphics,
                tabPage.Text,
                tabControl.Font,
                bounds,
                textColor,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
        };
    }

    private static Panel CreateHeaderWithCount(string text, Label countLabel)
    {
        var panel = new Panel
        {
            Dock = DockStyle.Fill,
            BackColor = Color.Transparent,
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
            BackColor = Color.Transparent,
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
        var profileMenu = BuildProfileContextMenu();
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            Padding = new Padding(12),
            BackColor = AppBackColor
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.ContextMenuStrip = profileMenu;
        tab.ContextMenuStrip = profileMenu;

        _profileTextBox = new TextBox
        {
            Multiline = true,
            MaxLength = 0,
            Visible = false
        };

        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, BackColor = AppBackColor, Padding = new Padding(0, 5, 0, 0) };
        _checkTokensButton = CreateButton("Check token", 120);
        _checkTokensButton.Click += async (_, _) => await CheckTokensAsync();
        var updateButton = CreateButton("Cập nhật", 110);
        updateButton.Click += (_, _) => ShowUpdateDialog();
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
        buttons.Controls.AddRange([_checkTokensButton, updateButton, saveDataButton, deleteCheckedButton, clearButton]);
        root.Controls.Add(buttons, 0, 0);

        _profileGrid = CreateGrid();
        _profileGrid.ContextMenuStrip = profileMenu;
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
        root.Controls.Add(_profileGrid, 0, 1);

        tab.Controls.Add(root);
        return tab;
    }

    private ContextMenuStrip BuildProfileContextMenu()
    {
        var menu = new ContextMenuStrip
        {
            Font = UiFont,
            BackColor = PanelBackColor,
            ForeColor = TextColor
        };
        var importItem = new ToolStripMenuItem("Nhập dữ liệu");
        importItem.Click += (_, _) => ShowProfileImportDialog();
        menu.Items.Add(importItem);
        return menu;
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

        _interactionActionTabs = new TabControl
        {
            Dock = DockStyle.Fill,
            Font = UiFontBold,
            Padding = new Point(12, 4)
        };
        StyleTabControl(_interactionActionTabs);
        _interactionActionTabs.TabPages.Add(BuildEditActionTab());
        _interactionActionTabs.TabPages.Add(BuildDeleteActionTab());
        _interactionActionTabs.TabPages.Add(BuildNewCommentActionTab());
        root.Controls.Add(_interactionActionTabs, 0, 0);

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
        _contentRowStyle = options.RowStyles[1];

        options.Controls.Add(CreateLabel("Số luồng:"), 0, 0);
        _threadsInput = new NumericUpDown { Dock = DockStyle.Left, Minimum = 1, Maximum = 200, Value = 5, Width = 100 };
        StyleNumeric(_threadsInput);
        options.Controls.Add(_threadsInput, 1, 0);

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
        options.SetColumnSpan(_editTextBox, 4);
        options.Controls.Add(_editTextBox, 1, 1);
        _toggleContentButton = CreateButton("Ẩn", dock: DockStyle.Fill);
        _toggleContentButton.Click += (_, _) => ToggleContentInput();
        options.Controls.Add(_toggleContentButton, 5, 1);

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
        foreach (DataGridViewColumn column in _logGrid.Columns)
        {
            column.SortMode = DataGridViewColumnSortMode.Programmatic;
        }

        _logGrid.ColumnHeaderMouseClick += LogGridColumnHeaderMouseClick;
        UpdateLogSortGlyphs();
        root.Controls.Add(_logGrid, 0, 3);

        tab.Controls.Add(root);
        return tab;
    }

    private TabPage BuildEditActionTab()
    {
        return BuildTwoInputActionTab(
            "Chỉnh sửa",
            "Link comment:",
            "Mỗi dòng 1 link comment hoặc comment_id",
            out _editUidTextBox,
            out _editLinksTextBox,
            out _editUidCountLabel,
            out _editLinkCountLabel);
    }

    private TabPage BuildDeleteActionTab()
    {
        return BuildTwoInputActionTab(
            "Xóa",
            "Link comment:",
            "Mỗi dòng 1 link comment hoặc comment_id",
            out _deleteUidTextBox,
            out _deleteLinksTextBox,
            out _deleteUidCountLabel,
            out _deleteLinkCountLabel);
    }

    private TabPage BuildNewCommentActionTab()
    {
        return BuildTwoInputActionTab(
            "Comment mới",
            "ID/link bài viết:",
            "Mỗi dòng 1 ID/link bài viết",
            out _commentUidTextBox,
            out _commentPostIdTextBox,
            out _commentUidCountLabel,
            out _commentPostCountLabel);
    }

    private TabPage BuildTwoInputActionTab(
        string title,
        string targetTitle,
        string targetPlaceholder,
        out TextBox uidTextBox,
        out TextBox targetTextBox,
        out Label uidCountLabel,
        out Label targetCountLabel)
    {
        var tab = new TabPage(title) { BackColor = AppBackColor };
        var inputGrid = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 2,
            BackColor = AppBackColor,
            Padding = new Padding(8)
        };
        inputGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 28));
        inputGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 72));
        inputGrid.RowStyles.Add(new RowStyle(SizeType.Absolute, 26));
        inputGrid.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        uidCountLabel = CreateCountLabel();
        targetCountLabel = CreateCountLabel();
        inputGrid.Controls.Add(CreateHeaderWithCount("UID profile (để trống = tự check bằng Graph):", uidCountLabel), 0, 0);
        inputGrid.Controls.Add(CreateHeaderWithCount(targetTitle, targetCountLabel), 1, 0);

        uidTextBox = CreateMultilineInput("Nhập 1 UID áp dụng tất cả, hoặc mỗi dòng 1 UID tương ứng link/post");
        targetTextBox = CreateMultilineInput(targetPlaceholder);
        uidTextBox.TextChanged += (_, _) => UpdateInteractionCounts();
        targetTextBox.TextChanged += (_, _) => UpdateInteractionCounts();
        inputGrid.Controls.Add(uidTextBox, 0, 1);
        inputGrid.Controls.Add(targetTextBox, 1, 1);

        tab.Controls.Add(inputGrid);
        return tab;
    }

    private static TextBox CreateMultilineInput(string placeholder)
    {
        var textBox = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            MaxLength = 0,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            Font = MonoFont,
            PlaceholderText = placeholder
        };
        StyleTextBox(textBox);
        return textBox;
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
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 274));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var inputs = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 4, RowCount = 6, BackColor = AppBackColor };
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 160));
        inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        for (var i = 0; i < 6; i++)
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

        inputs.Controls.Add(CreateLabel("Kiểm tra Proxy mỗi (giây):"), 0, 4);
        _proxyCheckIntervalInput = new NumericUpDown { Dock = DockStyle.Left, Minimum = 1, Maximum = 3600, Value = 5, Width = 90 };
        StyleNumeric(_proxyCheckIntervalInput);
        inputs.Controls.Add(_proxyCheckIntervalInput, 1, 4);

        var hint = new Label
        {
            Text = "Dùng placeholder {apiKey}. Dữ liệu nhạy cảm được lưu bằng Windows DPAPI theo user hiện tại.",
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            ForeColor = Color.FromArgb(75, 85, 99),
            BackColor = AppBackColor
        };
        inputs.SetColumnSpan(hint, 4);
        inputs.Controls.Add(hint, 0, 5);
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
        _proxyGrid.Columns.Add("ExpiresIn", "Còn hạn IP");
        _proxyGrid.Columns.Add("LastCheck", "Lần kiểm tra gần nhất");
        _proxyGrid.Columns.Add("Error", "Lỗi gần nhất");
        SetColumnWidths(_proxyGrid, 55, 180, 220, 100, 90, 120, 170, 120, 170, 420);
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

        _proxyCountdownTimer = new System.Windows.Forms.Timer { Interval = 1000 };
        _proxyCountdownTimer.Tick += (_, _) => UpdateProxyExpiryCountdown();
        _proxyCountdownTimer.Start();
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

    private void ShowUpdateDialog()
    {
        using var dialog = new UpdateDialog(_updateChecker);
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            _skipExitConfirm = true;
            Close();
        }
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

        var legacyActionIndex = Math.Clamp(_settings.InteractionActionIndex, 0, 2);
        _editUidTextBox.Text = !string.IsNullOrWhiteSpace(_settings.EditUidText)
            ? _settings.EditUidText
            : legacyActionIndex == 0 ? _settings.InteractionUidText : "";
        _editLinksTextBox.Text = !string.IsNullOrWhiteSpace(_settings.EditLinkText)
            ? _settings.EditLinkText
            : legacyActionIndex == 0 ? _settings.InteractionLinkText : "";
        _deleteUidTextBox.Text = !string.IsNullOrWhiteSpace(_settings.DeleteUidText)
            ? _settings.DeleteUidText
            : legacyActionIndex == 1 ? _settings.InteractionUidText : "";
        _deleteLinksTextBox.Text = !string.IsNullOrWhiteSpace(_settings.DeleteLinkText)
            ? _settings.DeleteLinkText
            : legacyActionIndex == 1 ? _settings.InteractionLinkText : "";
        _commentUidTextBox.Text = !string.IsNullOrWhiteSpace(_settings.NewCommentUidText)
            ? _settings.NewCommentUidText
            : legacyActionIndex == 2 ? _settings.InteractionUidText : "";
        _commentPostIdTextBox.Text = !string.IsNullOrWhiteSpace(_settings.NewCommentPostText)
            ? _settings.NewCommentPostText
            : _settings.InteractionPostIdText;
        _interactionActionTabs.SelectedIndex = legacyActionIndex;
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
        _proxyCheckIntervalInput.Value = Math.Clamp(_settings.ProxyCheckIntervalSeconds <= 0 ? 5 : _settings.ProxyCheckIntervalSeconds, (int)_proxyCheckIntervalInput.Minimum, (int)_proxyCheckIntervalInput.Maximum);
        UpdateInteractionCounts();
    }

    private void SaveAllSettings(bool showMessage)
    {
        _settings = new AppSettings
        {
            ProfileText = _profileTextBox.Text,
            ProfileStates = _profileManager.ExportStates(),
            InteractionUidText = GetCurrentUidTextBox().Text,
            InteractionLinkText = GetCurrentAction() is CommentActionKind.Edit or CommentActionKind.Delete ? GetCurrentTargetTextBox().Text : "",
            InteractionPostIdText = GetCurrentAction() == CommentActionKind.NewComment ? _commentPostIdTextBox.Text : "",
            InteractionActionIndex = _interactionActionTabs.SelectedIndex,
            EditUidText = _editUidTextBox.Text,
            EditLinkText = _editLinksTextBox.Text,
            DeleteUidText = _deleteUidTextBox.Text,
            DeleteLinkText = _deleteLinksTextBox.Text,
            NewCommentUidText = _commentUidTextBox.Text,
            NewCommentPostText = _commentPostIdTextBox.Text,
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
            UsesPerProxy = (int)_usesPerProxyInput.Value,
            ProxyCheckIntervalSeconds = (int)_proxyCheckIntervalInput.Value
        };
        _settingsStore.Save(_settings);
        _proxyManager.UpdateSettings(_settings);

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

    private void ShowProfileImportDialog()
    {
        using var dialog = new ProfileImportDialog(_profileTextBox.Text);
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }

        _profileTextBox.Text = dialog.InputText;
        LoadProfilesFromInput();
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

    private void ToggleContentInput()
    {
        _contentInputVisible = !_contentInputVisible;
        _editTextBox.Visible = _contentInputVisible;
        _contentRowStyle.Height = _contentInputVisible ? 88 : 36;
        _toggleContentButton.Text = _contentInputVisible ? "Ẩn" : "Hiện";
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

        var action = GetCurrentAction();
        var uids = ReadNonEmptyLines(GetCurrentUidTextBox().Text);

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
            var posts = ReadNonEmptyLines(_commentPostIdTextBox.Text)
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
            var links = ReadNonEmptyLines(GetCurrentTargetTextBox().Text);
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
        _logSortColumnName = "Index";
        _logSortDirection = SortOrder.Ascending;
        UpdateLogSortGlyphs();
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
        if (_editUidCountLabel is null ||
            _editLinkCountLabel is null ||
            _deleteUidCountLabel is null ||
            _deleteLinkCountLabel is null ||
            _commentUidCountLabel is null ||
            _commentPostCountLabel is null)
        {
            return;
        }

        _editUidCountLabel.Text = CountNonEmptyLines(_editUidTextBox.Text).ToString();
        _editLinkCountLabel.Text = CountNonEmptyLines(_editLinksTextBox.Text).ToString();
        _deleteUidCountLabel.Text = CountNonEmptyLines(_deleteUidTextBox.Text).ToString();
        _deleteLinkCountLabel.Text = CountNonEmptyLines(_deleteLinksTextBox.Text).ToString();
        _commentUidCountLabel.Text = CountNonEmptyLines(_commentUidTextBox.Text).ToString();
        _commentPostCountLabel.Text = CountNonEmptyLines(_commentPostIdTextBox.Text).ToString();
    }

    private CommentActionKind GetCurrentAction()
    {
        return _interactionActionTabs.SelectedIndex switch
        {
            1 => CommentActionKind.Delete,
            2 => CommentActionKind.NewComment,
            _ => CommentActionKind.Edit
        };
    }

    private TextBox GetCurrentUidTextBox()
    {
        return GetCurrentAction() switch
        {
            CommentActionKind.Delete => _deleteUidTextBox,
            CommentActionKind.NewComment => _commentUidTextBox,
            _ => _editUidTextBox
        };
    }

    private TextBox GetCurrentTargetTextBox()
    {
        return GetCurrentAction() switch
        {
            CommentActionKind.Delete => _deleteLinksTextBox,
            CommentActionKind.NewComment => _commentPostIdTextBox,
            _ => _editLinksTextBox
        };
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
                DisplayProfileStatus(profile.TokenStatus),
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

            row.Cells["Status"].Value = DisplayProfileStatus(status);
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
        row.DefaultCellStyle.SelectionBackColor = ControlPaint.Dark(backgroundColor, 0.25F);
        row.DefaultCellStyle.SelectionForeColor = Color.White;
        row.Cells["Status"].Style.ForeColor = statusColor;
        row.Cells["Status"].Style.Font = UiFontBold;
        row.Cells["Error"].Style.ForeColor = statusColor;
        row.Cells["Error"].Style.Font = UiFontBold;
    }

    private static Color GetProfileStatusColor(string status)
    {
        if (status.Contains("Token out", StringComparison.OrdinalIgnoreCase))
        {
            return WarningColor;
        }

        if (status.Contains("Live", StringComparison.OrdinalIgnoreCase) ||
            status.Contains("Sống", StringComparison.OrdinalIgnoreCase))
        {
            return SuccessColor;
        }

        if (status.Contains("Die", StringComparison.OrdinalIgnoreCase) ||
            status.Contains("Checkpoint", StringComparison.OrdinalIgnoreCase) ||
            status.Contains("Chết", StringComparison.OrdinalIgnoreCase))
        {
            return DangerColor;
        }

        return TextColor;
    }

    private static Color GetProfileStatusBackColor(string status)
    {
        if (status.Contains("Token out", StringComparison.OrdinalIgnoreCase))
        {
            return Color.FromArgb(253, 224, 135);
        }

        if (status.Contains("Live", StringComparison.OrdinalIgnoreCase) ||
            status.Contains("Sống", StringComparison.OrdinalIgnoreCase))
        {
            return Color.FromArgb(187, 247, 208);
        }

        if (status.Contains("Die", StringComparison.OrdinalIgnoreCase) ||
            status.Contains("Checkpoint", StringComparison.OrdinalIgnoreCase) ||
            status.Contains("Chết", StringComparison.OrdinalIgnoreCase))
        {
            return Color.FromArgb(254, 202, 202);
        }

        return PanelBackColor;
    }

    private static string DisplayProfileStatus(string status)
    {
        if (string.IsNullOrWhiteSpace(status))
        {
            return "";
        }

        return status switch
        {
            var value when value.Equals("Chua kiem tra", StringComparison.OrdinalIgnoreCase) => "Chưa kiểm tra",
            var value when value.Equals("Da nap", StringComparison.OrdinalIgnoreCase) => "Đã nạp",
            var value when value.Equals("Da refresh token", StringComparison.OrdinalIgnoreCase) => "Đã cập nhật token",
            var value when value.Equals("Live", StringComparison.OrdinalIgnoreCase) => "Sống",
            var value when value.StartsWith("Die", StringComparison.OrdinalIgnoreCase) => value.Replace("Die", "Chết", StringComparison.OrdinalIgnoreCase),
            var value when value.StartsWith("Token out", StringComparison.OrdinalIgnoreCase) => value.Replace("Token out", "Token hết hạn", StringComparison.OrdinalIgnoreCase),
            _ => status
        };
    }

    private static string DisplayProxyStatus(string status)
    {
        return status switch
        {
            "Stopped" => "Đã dừng",
            "Starting" => "Đang khởi động",
            "GettingNew" => "Đang lấy IP mới",
            "Refreshing" => "Đang lấy IP mới",
            "Waiting" => "Đang chờ",
            "Ready" => "Sẵn sàng",
            "Error" => "Lỗi",
            _ => status
        };
    }

    private static string DisplayLogAction(string action)
    {
        return action switch
        {
            "Edit" => "Chỉnh sửa",
            "Delete" => "Xóa",
            "Comment moi" => "Comment mới",
            _ => action
        };
    }

    private static string DisplayProxyText(string proxy)
    {
        return string.Equals(proxy, "Direct", StringComparison.OrdinalIgnoreCase)
            ? "Không proxy"
            : proxy;
    }

    private static string DisplayLogStatus(string status)
    {
        return status switch
        {
            "Thanh cong" => "Thành công",
            "That bai" => "Thất bại",
            "Cho chay" => "Chờ chạy",
            "Dang chay" => "Đang chạy",
            "Dang cho proxy" => "Đang chờ proxy",
            "Dung" => "Đã dừng",
            "Dung profile" => "Dừng profile",
            var value when value.StartsWith("Token out", StringComparison.OrdinalIgnoreCase) => value.Replace("Token out", "Token hết hạn", StringComparison.OrdinalIgnoreCase),
            var value when value.StartsWith("Die", StringComparison.OrdinalIgnoreCase) => value.Replace("Die", "Chết", StringComparison.OrdinalIgnoreCase),
            _ => status
        };
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
                DisplayProxyStatus(proxy.Status),
                proxy.LastGetIpAt?.ToString("yyyy-MM-dd HH:mm:ss") ?? "",
                FormatProxyIpExpiresIn(proxy.IpExpiresAt),
                proxy.LastCheckedAt?.ToString("yyyy-MM-dd HH:mm:ss") ?? "",
                proxy.LastError);
        }
    }

    private void UpdateProxyExpiryCountdown()
    {
        if (_proxyGrid is null || _proxyGrid.Rows.Count == 0)
        {
            return;
        }

        var proxiesByIndex = _proxyManager.Snapshot()
            .ToDictionary(proxy => proxy.Index);
        foreach (DataGridViewRow row in _proxyGrid.Rows)
        {
            if (!int.TryParse(row.Cells["Index"].Value?.ToString(), out var index) ||
                !proxiesByIndex.TryGetValue(index, out var proxy))
            {
                continue;
            }

            row.Cells["ExpiresIn"].Value = FormatProxyIpExpiresIn(proxy.IpExpiresAt);
        }
    }

    private static string FormatProxyIpExpiresIn(DateTime? expiresAt)
    {
        if (expiresAt is null)
        {
            return "";
        }

        var remaining = expiresAt.Value - DateTime.Now;
        if (remaining <= TimeSpan.Zero)
        {
            return "Hết hạn";
        }

        return remaining.TotalHours >= 1
            ? $"{(int)remaining.TotalHours:00}:{remaining.Minutes:00}:{remaining.Seconds:00}"
            : $"{remaining.Minutes:00}:{remaining.Seconds:00}";
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
                DisplayLogAction(entry.Action),
                DisplayProxyText(entry.Proxy),
                DisplayLogStatus(entry.Status),
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

            row.Cells["Action"].Value = DisplayLogAction(entry.Action);
            row.Cells["Proxy"].Value = DisplayProxyText(entry.Proxy);
            row.Cells["Status"].Value = DisplayLogStatus(entry.Status);
            row.Cells["Error"].Value = entry.Error;
        }

        ApplyLogRowStyle(row);
        ApplyCurrentLogSort();
    }

    private void LogGridColumnHeaderMouseClick(object? sender, DataGridViewCellMouseEventArgs e)
    {
        if (e.ColumnIndex < 0)
        {
            return;
        }

        var columnName = _logGrid.Columns[e.ColumnIndex].Name;
        if (_logSortColumnName.Equals(columnName, StringComparison.OrdinalIgnoreCase))
        {
            _logSortDirection = _logSortDirection == SortOrder.Descending
                ? SortOrder.Ascending
                : SortOrder.Descending;
        }
        else
        {
            _logSortColumnName = columnName;
            _logSortDirection = SortOrder.Ascending;
        }

        ApplyCurrentLogSort();
        UpdateLogSortGlyphs();
    }

    private void ApplyCurrentLogSort()
    {
        if (_logGrid.Rows.Count <= 1)
        {
            return;
        }

        _logGrid.SuspendLayout();
        try
        {
            _logGrid.Sort(new LogRowComparer(_logSortColumnName, _logSortDirection));
        }
        finally
        {
            _logGrid.ResumeLayout();
        }
    }

    private void UpdateLogSortGlyphs()
    {
        if (_logGrid.Columns.Count == 0)
        {
            return;
        }

        foreach (DataGridViewColumn column in _logGrid.Columns)
        {
            column.HeaderCell.SortGlyphDirection = SortOrder.None;
        }

        if (_logGrid.Columns[_logSortColumnName] is { } sortColumn)
        {
            sortColumn.HeaderCell.SortGlyphDirection = _logSortDirection;
        }
    }

    private static int GetLogStatusSortRank(string status)
    {
        return status switch
        {
            var value when value.Contains("Thanh cong", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Thành công", StringComparison.OrdinalIgnoreCase) => 0,
            var value when value.Contains("Dang chay", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Đang chạy", StringComparison.OrdinalIgnoreCase) => 1,
            var value when value.Contains("Cho chay", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Chờ chạy", StringComparison.OrdinalIgnoreCase) => 2,
            var value when value.Contains("Dang cho proxy", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Đang chờ proxy", StringComparison.OrdinalIgnoreCase) => 3,
            _ => 4
        };
    }

    private sealed class LogRowComparer(string columnName, SortOrder direction) : System.Collections.IComparer
    {
        public int Compare(object? x, object? y)
        {
            var left = (DataGridViewRow)x!;
            var right = (DataGridViewRow)y!;
            var leftIndex = GetRowIndex(left);
            var rightIndex = GetRowIndex(right);
            var compare = CompareByColumn(left, right, columnName);

            if (compare == 0)
            {
                compare = leftIndex.CompareTo(rightIndex);
            }

            return direction == SortOrder.Descending ? -compare : compare;
        }

        private static int CompareByColumn(DataGridViewRow left, DataGridViewRow right, string columnName)
        {
            if (columnName.Equals("Status", StringComparison.OrdinalIgnoreCase))
            {
                var leftRank = GetLogStatusSortRank(left.Cells["Status"].Value?.ToString() ?? "");
                var rightRank = GetLogStatusSortRank(right.Cells["Status"].Value?.ToString() ?? "");
                var rankCompare = leftRank.CompareTo(rightRank);
                if (rankCompare != 0)
                {
                    return rankCompare;
                }
            }

            if (left.DataGridView?.Columns.Contains(columnName) != true ||
                right.DataGridView?.Columns.Contains(columnName) != true)
            {
                return 0;
            }

            var leftText = left.Cells[columnName].Value?.ToString() ?? "";
            var rightText = right.Cells[columnName].Value?.ToString() ?? "";
            if (decimal.TryParse(leftText, out var leftNumber) &&
                decimal.TryParse(rightText, out var rightNumber))
            {
                return leftNumber.CompareTo(rightNumber);
            }

            return string.Compare(leftText, rightText, StringComparison.CurrentCultureIgnoreCase);
        }

        private static int GetRowIndex(DataGridViewRow row)
        {
            return int.TryParse(row.Cells["Index"].Value?.ToString(), out var value) ? value : 0;
        }
    }

    private static void ApplyLogRowStyle(DataGridViewRow row)
    {
        var status = row.Cells["Status"].Value?.ToString() ?? "";
        var (color, backgroundColor) = status switch
        {
            var value when value.Contains("Thanh cong", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Thành công", StringComparison.OrdinalIgnoreCase) => (SuccessColor, Color.FromArgb(187, 247, 208)),
            var value when value.Contains("That bai", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Thất bại", StringComparison.OrdinalIgnoreCase) => (DangerColor, Color.FromArgb(254, 202, 202)),
            var value when value.Contains("Token out", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Token hết hạn", StringComparison.OrdinalIgnoreCase) => (WarningColor, Color.FromArgb(253, 224, 135)),
            var value when value.Contains("Die", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Chết", StringComparison.OrdinalIgnoreCase) => (DangerColor, Color.FromArgb(254, 202, 202)),
            var value when value.Contains("Checkpoint", StringComparison.OrdinalIgnoreCase) => (DangerColor, Color.FromArgb(254, 202, 202)),
            var value when value.Contains("Dang cho proxy", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Đang chờ proxy", StringComparison.OrdinalIgnoreCase) => (WarningColor, Color.FromArgb(253, 224, 135)),
            var value when value.Contains("Dang chay", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Đang chạy", StringComparison.OrdinalIgnoreCase) => (PrimaryDarkColor, Color.FromArgb(191, 219, 254)),
            var value when value.Contains("Cho chay", StringComparison.OrdinalIgnoreCase) ||
                           value.Contains("Chờ chạy", StringComparison.OrdinalIgnoreCase) => (Color.FromArgb(55, 65, 81), Color.FromArgb(229, 231, 235)),
            _ => (TextColor, PanelBackColor)
        };

        row.DefaultCellStyle.BackColor = backgroundColor;
        row.DefaultCellStyle.SelectionBackColor = ControlPaint.Dark(backgroundColor, 0.25F);
        row.DefaultCellStyle.SelectionForeColor = Color.White;
        row.DefaultCellStyle.ForeColor = TextColor;
        row.Cells["Status"].Style.ForeColor = color;
        row.Cells["Status"].Style.Font = UiFontBold;
        row.Cells["Error"].Style.ForeColor = color;
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
        grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(37, 99, 235);
        grid.DefaultCellStyle.SelectionForeColor = Color.White;
        grid.DefaultCellStyle.Font = UiFont;
        grid.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(239, 246, 255);
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
        if (_skipExitConfirm)
        {
            SaveAllSettings(showMessage: false);
            _proxyCountdownTimer?.Stop();
            _proxyCountdownTimer?.Dispose();
            _taskManager.Stop();
            _proxyManager.Stop();
            base.OnFormClosing(e);
            return;
        }

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
        _proxyCountdownTimer?.Stop();
        _proxyCountdownTimer?.Dispose();
        _taskManager.Stop();
        _proxyManager.Stop();
        base.OnFormClosing(e);
    }
}

public sealed record TokenCheckResult(string Status, string Error);
