namespace ToolEditDeleteCmt;

public sealed class CheckBoxHeaderCell : DataGridViewColumnHeaderCell
{
    public bool Checked { get; private set; }

    protected override void Paint(
        Graphics graphics,
        Rectangle clipBounds,
        Rectangle cellBounds,
        int rowIndex,
        DataGridViewElementStates dataGridViewElementState,
        object? value,
        object? formattedValue,
        string? errorText,
        DataGridViewCellStyle cellStyle,
        DataGridViewAdvancedBorderStyle advancedBorderStyle,
        DataGridViewPaintParts paintParts)
    {
        base.Paint(
            graphics,
            clipBounds,
            cellBounds,
            rowIndex,
            dataGridViewElementState,
            null,
            string.Empty,
            errorText,
            cellStyle,
            advancedBorderStyle,
            paintParts & ~DataGridViewPaintParts.ContentForeground);

        var state = Checked ? ButtonState.Checked : ButtonState.Normal;
        var size = CheckBoxRenderer.GetGlyphSize(graphics, Checked
            ? System.Windows.Forms.VisualStyles.CheckBoxState.CheckedNormal
            : System.Windows.Forms.VisualStyles.CheckBoxState.UncheckedNormal);
        var boxBounds = new Rectangle(
            cellBounds.Left + (cellBounds.Width - size.Width) / 2,
            cellBounds.Top + (cellBounds.Height - size.Height) / 2,
            size.Width,
            size.Height);

        ControlPaint.DrawCheckBox(graphics, boxBounds, state);
    }

    protected override void OnMouseClick(DataGridViewCellMouseEventArgs e)
    {
        base.OnMouseClick(e);

        if (DataGridView is null || e.Button != MouseButtons.Left)
        {
            return;
        }

        var targetChecked = !Checked;
        DataGridView.EndEdit();
        SetChecked(targetChecked);
        foreach (DataGridViewRow row in DataGridView.Rows)
        {
            if (!row.IsNewRow)
            {
                row.Cells[ColumnIndex].Value = targetChecked;
            }
        }

        SetChecked(targetChecked);
        DataGridView.NotifyCurrentCellDirty(false);
        DataGridView.InvalidateColumn(ColumnIndex);
        DataGridView.Refresh();
    }

    public void SetChecked(bool value)
    {
        Checked = value;
        DataGridView?.InvalidateCell(this);
    }
}
