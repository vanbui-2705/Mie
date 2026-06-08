using System.ComponentModel;
using System.Drawing.Drawing2D;

namespace ToolEditDeleteCmt;

public sealed class RoundedButton : Button
{
    private bool _hovered;
    private bool _pressed;

    public RoundedButton()
    {
        SetStyle(
            ControlStyles.UserPaint |
            ControlStyles.AllPaintingInWmPaint |
            ControlStyles.OptimizedDoubleBuffer |
            ControlStyles.ResizeRedraw,
            true);
        FlatStyle = FlatStyle.Flat;
        FlatAppearance.BorderSize = 0;
    }

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public int CornerRadius { get; set; } = 7;

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color ButtonColor { get; set; } = Color.FromArgb(6, 182, 212);

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color ButtonHoverColor { get; set; } = Color.FromArgb(34, 211, 238);

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color ButtonPressedColor { get; set; } = Color.FromArgb(8, 145, 178);

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color ButtonDisabledColor { get; set; } = Color.FromArgb(156, 163, 175);

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color ButtonBorderColor { get; set; } = Color.FromArgb(8, 145, 178);

    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color ButtonShadowColor { get; set; } = Color.FromArgb(90, 8, 145, 178);

    protected override void OnMouseEnter(EventArgs e)
    {
        _hovered = true;
        Invalidate();
        base.OnMouseEnter(e);
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        _hovered = false;
        _pressed = false;
        Invalidate();
        base.OnMouseLeave(e);
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        if (e.Button == MouseButtons.Left)
        {
            _pressed = true;
            Invalidate();
        }

        base.OnMouseDown(e);
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        _pressed = false;
        Invalidate();
        base.OnMouseUp(e);
    }

    protected override void OnEnabledChanged(EventArgs e)
    {
        Invalidate();
        base.OnEnabledChanged(e);
    }

    protected override void OnPaint(PaintEventArgs pevent)
    {
        var graphics = pevent.Graphics;
        graphics.SmoothingMode = SmoothingMode.AntiAlias;
        graphics.Clear(Parent?.BackColor ?? SystemColors.Control);

        var shadowRect = new Rectangle(2, 4, Width - 5, Height - 6);
        using (var shadowPath = RoundedRect(shadowRect, CornerRadius))
        using (var shadowBrush = new SolidBrush(ButtonShadowColor))
        {
            graphics.FillPath(shadowBrush, shadowPath);
        }

        var topOffset = _pressed ? 3 : _hovered ? 0 : 1;
        var buttonRect = new Rectangle(0, topOffset, Width - 4, Height - 6);
        var fillColor = !Enabled
            ? ButtonDisabledColor
            : _pressed
                ? ButtonPressedColor
                : _hovered
                    ? ButtonHoverColor
                    : ButtonColor;

        using (var path = RoundedRect(buttonRect, CornerRadius))
        using (var brush = new SolidBrush(fillColor))
        using (var pen = new Pen(Enabled ? ButtonBorderColor : ButtonDisabledColor))
        {
            graphics.FillPath(brush, path);
            graphics.DrawPath(pen, path);
        }

        TextRenderer.DrawText(
            graphics,
            Text,
            Font,
            buttonRect,
            ForeColor,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
    }

    private static GraphicsPath RoundedRect(Rectangle bounds, int radius)
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
