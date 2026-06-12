namespace ToolEditDeleteCmt;

public sealed class UpdateDialog : Form
{
    private static readonly Color AppBackColor = Color.FromArgb(232, 241, 255);
    private static readonly Color PrimaryColor = Color.FromArgb(8, 102, 255);
    private static readonly Color DangerColor = Color.FromArgb(220, 38, 38);
    private static readonly Color WarningColor = Color.FromArgb(217, 119, 6);
    private static readonly Color TextColor = Color.FromArgb(17, 24, 39);
    private static readonly Font UiFont = new("Segoe UI", 9F);
    private static readonly Font UiFontBold = new("Segoe UI Semibold", 9F);

    private readonly GitHubUpdateChecker _updateChecker;
    private readonly Label _statusLabel = new();
    private readonly ListView _versionList = new();
    private readonly TextBox _releaseNotesTextBox = new();
    private readonly Button _updateButton = new();
    private readonly Button _cancelButton = new();
    private readonly ProgressBar _progressBar = new();
    private List<UpdateReleaseInfo> _releases = [];
    private UpdateReleaseInfo? _latestUpdate;
    private bool _loading;

    public UpdateDialog(GitHubUpdateChecker updateChecker)
    {
        _updateChecker = updateChecker;

        Text = "Cập nhật FlowMeta";
        StartPosition = FormStartPosition.CenterParent;
        MinimumSize = new Size(820, 560);
        Size = new Size(900, 640);
        BackColor = AppBackColor;
        Font = UiFont;

        BuildUi();
        Shown += async (_, _) => await LoadReleasesAsync();
    }

    private void BuildUi()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 5,
            Padding = new Padding(14),
            BackColor = AppBackColor
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));

        var title = new Label
        {
            Dock = DockStyle.Fill,
            Text = $"Phiên bản hiện tại: {_updateChecker.CurrentVersionText}",
            ForeColor = TextColor,
            Font = new Font("Segoe UI Semibold", 13F),
            TextAlign = ContentAlignment.MiddleLeft
        };
        root.Controls.Add(title, 0, 0);

        _statusLabel.Dock = DockStyle.Fill;
        _statusLabel.Text = "Đang tải thông tin cập nhật...";
        _statusLabel.ForeColor = PrimaryColor;
        _statusLabel.Font = UiFontBold;
        _statusLabel.TextAlign = ContentAlignment.MiddleLeft;
        root.Controls.Add(_statusLabel, 0, 1);

        var content = new SplitContainer
        {
            Dock = DockStyle.Fill,
            Orientation = Orientation.Vertical,
            SplitterDistance = 330,
            BackColor = AppBackColor
        };

        _versionList.Dock = DockStyle.Fill;
        _versionList.View = View.Details;
        _versionList.FullRowSelect = true;
        _versionList.MultiSelect = false;
        _versionList.HideSelection = false;
        _versionList.Columns.Add("Version", 90);
        _versionList.Columns.Add("Ngày", 120);
        _versionList.Columns.Add("Trạng thái", 110);
        _versionList.SelectedIndexChanged += (_, _) => DisplaySelectedRelease();
        content.Panel1.Controls.Add(_versionList);

        _releaseNotesTextBox.Dock = DockStyle.Fill;
        _releaseNotesTextBox.Multiline = true;
        _releaseNotesTextBox.ReadOnly = true;
        _releaseNotesTextBox.ScrollBars = ScrollBars.Both;
        _releaseNotesTextBox.WordWrap = true;
        _releaseNotesTextBox.BorderStyle = BorderStyle.FixedSingle;
        content.Panel2.Controls.Add(_releaseNotesTextBox);

        root.Controls.Add(content, 0, 2);

        _progressBar.Dock = DockStyle.Fill;
        _progressBar.Minimum = 0;
        _progressBar.Maximum = 100;
        _progressBar.Visible = false;
        root.Controls.Add(_progressBar, 0, 3);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            BackColor = AppBackColor,
            Padding = new Padding(0, 7, 0, 0)
        };
        ConfigureButton(_cancelButton, "Hủy", DangerColor);
        _cancelButton.Click += (_, _) =>
        {
            DialogResult = DialogResult.Cancel;
            Close();
        };
        ConfigureButton(_updateButton, "Cập nhật", PrimaryColor);
        _updateButton.Enabled = false;
        _updateButton.Click += async (_, _) => await DownloadAndInstallAsync();
        buttons.Controls.Add(_cancelButton);
        buttons.Controls.Add(_updateButton);
        root.Controls.Add(buttons, 0, 4);

        Controls.Add(root);
    }

    private static void ConfigureButton(Button button, string text, Color color)
    {
        button.Text = text;
        button.Width = 110;
        button.Height = 32;
        button.BackColor = color;
        button.ForeColor = Color.White;
        button.FlatStyle = FlatStyle.Flat;
        button.Font = UiFontBold;
        button.Cursor = Cursors.Hand;
        button.UseVisualStyleBackColor = false;
        button.Margin = new Padding(8, 0, 0, 0);
    }

    private async Task LoadReleasesAsync()
    {
        if (_loading)
        {
            return;
        }

        _loading = true;
        _updateButton.Enabled = false;
        _versionList.Items.Clear();
        _releaseNotesTextBox.Clear();
        _statusLabel.ForeColor = PrimaryColor;
        _statusLabel.Text = "Đang tải thông tin cập nhật...";

        try
        {
            var result = await _updateChecker.GetReleaseHistoryAsync();
            if (!result.IsSuccess)
            {
                _statusLabel.ForeColor = DangerColor;
                _statusLabel.Text = result.Message;
                return;
            }

            _releases = result.Releases;
            _latestUpdate = result.LatestUpdate;
            foreach (var release in _releases)
            {
                var item = new ListViewItem(release.TagName);
                item.SubItems.Add(release.PublishedAt.LocalDateTime.ToString("dd/MM/yyyy"));
                item.SubItems.Add(release.IsNewerThanCurrent ? "Bản mới" : "Đã có");
                item.Tag = release;
                if (release.IsNewerThanCurrent)
                {
                    item.ForeColor = WarningColor;
                }

                _versionList.Items.Add(item);
            }

            if (_versionList.Items.Count > 0)
            {
                _versionList.Items[0].Selected = true;
            }

            _statusLabel.ForeColor = _latestUpdate is null ? PrimaryColor : WarningColor;
            _statusLabel.Text = result.Message;
            _updateButton.Enabled = _latestUpdate is not null;
        }
        catch (Exception ex)
        {
            _statusLabel.ForeColor = DangerColor;
            _statusLabel.Text = $"Không kiểm tra được cập nhật: {ex.Message}";
        }
        finally
        {
            _loading = false;
        }
    }

    private void DisplaySelectedRelease()
    {
        if (_versionList.SelectedItems.Count == 0 ||
            _versionList.SelectedItems[0].Tag is not UpdateReleaseInfo release)
        {
            _releaseNotesTextBox.Clear();
            return;
        }

        var title = string.IsNullOrWhiteSpace(release.Name) ? release.TagName : release.Name;
        var body = string.IsNullOrWhiteSpace(release.Body)
            ? "Không có nội dung cập nhật."
            : release.Body.Replace("\\n", Environment.NewLine);
        _releaseNotesTextBox.Text =
            $"{title}{Environment.NewLine}" +
            $"Ngày phát hành: {release.PublishedAt.LocalDateTime:dd/MM/yyyy HH:mm}{Environment.NewLine}" +
            $"{new string('-', 60)}{Environment.NewLine}" +
            body;
    }

    private async Task DownloadAndInstallAsync()
    {
        var release = _latestUpdate;
        if (release is null)
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(release.DownloadUrl))
        {
            MessageBox.Show(this, "Release mới nhất chưa có file FlowMeta.exe.", "Cập nhật FlowMeta", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        var confirm = MessageBox.Show(
            this,
            $"Cập nhật lên {release.TagName}?{Environment.NewLine}Tool sẽ tải bản mới, đóng app, thay file exe và mở lại.",
            "Cập nhật FlowMeta",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question);
        if (confirm != DialogResult.Yes)
        {
            return;
        }

        _updateButton.Enabled = false;
        _cancelButton.Enabled = false;
        _progressBar.Visible = true;
        _progressBar.Value = 0;
        _statusLabel.ForeColor = PrimaryColor;
        _statusLabel.Text = "Đang tải bản cập nhật...";

        try
        {
            var progress = new Progress<int>(value =>
            {
                _progressBar.Value = Math.Clamp(value, 0, 100);
                _statusLabel.Text = $"Đang tải bản cập nhật... {_progressBar.Value}%";
            });
            var downloadedPath = await _updateChecker.DownloadUpdateAsync(release, progress);
            UpdateInstaller.ScheduleInstall(downloadedPath);
            MessageBox.Show(
                this,
                "Tải xong bản cập nhật. FlowMeta sẽ đóng, tự cập nhật và mở lại.",
                "Cập nhật FlowMeta",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (Exception ex)
        {
            _cancelButton.Enabled = true;
            _updateButton.Enabled = true;
            _statusLabel.ForeColor = DangerColor;
            _statusLabel.Text = $"Cập nhật lỗi: {ex.Message}";
            MessageBox.Show(this, ex.Message, "Cập nhật FlowMeta", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
