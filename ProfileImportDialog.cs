namespace ToolEditDeleteCmt;

public sealed class ProfileImportDialog : Form
{
    private static readonly Color AppBackColor = Color.FromArgb(232, 241, 255);
    private static readonly Color PrimaryColor = Color.FromArgb(8, 102, 255);
    private static readonly Color TextColor = Color.FromArgb(17, 24, 39);
    private static readonly Font UiFont = new("Segoe UI", 9F);
    private static readonly Font UiFontBold = new("Segoe UI Semibold", 9F);
    private static readonly Font MonoFont = new("Consolas", 9.5F);

    private readonly TextBox _inputTextBox = new();

    public ProfileImportDialog(string currentText)
    {
        Text = "Nhập dữ liệu hồ sơ";
        StartPosition = FormStartPosition.CenterParent;
        MinimumSize = new Size(760, 520);
        Size = new Size(900, 620);
        BackColor = AppBackColor;
        Font = UiFont;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(16),
            BackColor = AppBackColor
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));

        root.Controls.Add(new Label
        {
            Dock = DockStyle.Fill,
            Text = "Nhập dữ liệu theo định dạng uid|token",
            ForeColor = TextColor,
            Font = UiFontBold,
            TextAlign = ContentAlignment.MiddleLeft
        }, 0, 0);

        _inputTextBox.Dock = DockStyle.Fill;
        _inputTextBox.Multiline = true;
        _inputTextBox.MaxLength = 0;
        _inputTextBox.ScrollBars = ScrollBars.Both;
        _inputTextBox.WordWrap = false;
        _inputTextBox.Font = MonoFont;
        _inputTextBox.BorderStyle = BorderStyle.FixedSingle;
        _inputTextBox.Text = currentText;
        _inputTextBox.PlaceholderText = "uid|token";
        root.Controls.Add(_inputTextBox, 0, 1);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            BackColor = AppBackColor,
            Padding = new Padding(0, 8, 0, 0)
        };
        var okButton = new Button
        {
            Text = "OK",
            Width = 200,
            Height = 34,
            BackColor = PrimaryColor,
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat,
            Font = UiFontBold,
            Cursor = Cursors.Hand,
            UseVisualStyleBackColor = false
        };
        okButton.Click += (_, _) =>
        {
            DialogResult = DialogResult.OK;
            Close();
        };
        buttons.Controls.Add(okButton);
        root.Controls.Add(buttons, 0, 2);

        Controls.Add(root);
        AcceptButton = okButton;
    }

    public string InputText => _inputTextBox.Text;
}
