using System.ComponentModel;
using System.Drawing.Drawing2D;

namespace ToolEditDeleteCmt;

public sealed class FlatTabControl : TabControl
{
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color StripBackColor { get; set; } = Color.FromArgb(232, 241, 255);

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color TabBackColor { get; set; } = Color.White;

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color SelectedTabBackColor { get; set; } = Color.FromArgb(219, 234, 254);

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color TextColor { get; set; } = Color.FromArgb(17, 24, 39);

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color SelectedTextColor { get; set; } = Color.FromArgb(8, 102, 255);

    public FlatTabControl()
    {
        SetStyle(
            ControlStyles.UserPaint |
            ControlStyles.AllPaintingInWmPaint |
            ControlStyles.OptimizedDoubleBuffer |
            ControlStyles.ResizeRedraw,
            true);
        DrawMode = TabDrawMode.OwnerDrawFixed;
        SizeMode = TabSizeMode.Fixed;
        ItemSize = new Size(116, 36);
        Padding = new Point(0, 0);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.Clear(StripBackColor);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;

        for (var i = 0; i < TabPages.Count; i++)
        {
            DrawTab(e.Graphics, i);
        }
    }

    private void DrawTab(Graphics graphics, int index)
    {
        var selected = index == SelectedIndex;
        var tabBounds = GetTabRect(index);
        var pillBounds = new Rectangle(
            tabBounds.X + 6,
            tabBounds.Y + 6,
            tabBounds.Width - 12,
            tabBounds.Height - 12);

        using var brush = new SolidBrush(selected ? SelectedTabBackColor : TabBackColor);
        using var path = CreateRoundRectanglePath(pillBounds, 6);
        graphics.FillPath(brush, path);

        TextRenderer.DrawText(
            graphics,
            TabPages[index].Text,
            Font,
            pillBounds,
            selected ? SelectedTextColor : TextColor,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
    }

    private static GraphicsPath CreateRoundRectanglePath(Rectangle bounds, int radius)
    {
        var diameter = radius * 2;
        var path = new GraphicsPath();
        path.AddArc(bounds.Left, bounds.Top, diameter, diameter, 180, 90);
        path.AddArc(bounds.Right - diameter, bounds.Top, diameter, diameter, 270, 90);
        path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
        path.AddArc(bounds.Left, bounds.Bottom - diameter, diameter, diameter, 90, 90);
        path.CloseFigure();
        return path;
    }
}
