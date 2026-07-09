# FlowMeta — Frontend Design Spec

> Tài liệu thiết kế UX/UI cho ứng dụng FlowMeta (WinForms .NET 9).
> File này là single source of truth cho mọi quyết định giao diện — không cần đọc code để hiểu design.

---

## 1. Product & Audience

| | |
|---|---|
| **Product** | FlowMeta — desktop tool quản lý tác vụ comment Facebook (edit / delete / new comment) + proxy rotation |
| **Audience** | Operator automation Việt Nam, dùng tool cả ngày, cần tốc độ + độ chính xác |
| **Single job** | Cho operator thấy rõ trạng thái từng profile + từng task, bắt đầu/dừng tác vụ chỉ với 1-2 click |

---

## 2. Design Direction: "Precision Instrument"

Giao diện như một công cụ chuyên nghiệp — không rực rỡ, không yếu đuối. Màu sắc lạnh + sắc nét, giống phần mềm điều khiển máy bay / DAW. Chỉ một điểm nhấn ấm (amber) để báo lỗi/warning — như đèn cảnh báo trong cabin.

---

## 3. Color Palette — "Frost"

```csharp
// Nền & Surface
AppBack      = #F8FAFC   // slate-50 — nền chính, rất nhẹ
Panel        = #FFFFFF   // trắng — card, panel nổi
SurfaceRow   = #F1F5F9   // slate-100 — hàng xen kẽ grid
SurfaceDark  = #1E293B   // slate-800 — header grid, eyebrow

// Brand
Accent       = #2563EB   // blue-600 — nút chính, highlight
AccentHover  = #1D4ED8   // blue-700
AccentSoft   = #DBEAFE   // blue-100 — badge, tag

// Text
Text         = #0F172A   // slate-900
TextSub      = #64748B   // slate-500

// Trạng thái
Success      = #059669   // emerald-600
SuccessSoft  = #D1FAE5   // emerald-100
Warning      = #D97706   // amber-600  ← ĐIỂM NHẤN ẤM DUY NHẤT
WarningSoft  = #FEF3C7   // amber-100
Danger       = #DC2626   // red-600
DangerSoft   = #FEE2E2   // red-100
Info         = #0891B2   // cyan-600 (proxy waiting, đang chạy)
InfoSoft     = #CFFAFE   // cyan-100

// Viền & phân cách
Border       = #E2E8F0   // slate-200
Divider      = #F1F5F9   // slate-100 — mảnh hơn border
```

### Quy tắc dùng màu

| Vùng | Màu nền | Màu chữ | Ghi chú |
|---|---|---|---|
| Form chính | `AppBack` | `Text` | |
| Panel/card | `Panel` | `Text` | |
| Header grid | `SurfaceDark` | `#FFF` | Dark header tạo độ sâu |
| Hàng chẵn grid | `Panel` | `Text` | |
| Hàng lẻ grid | `SurfaceRow` | `Text` | |
| Button chính | `Accent` | `#FFF` | |
| Button dừng/xóa | `Danger` | `#FFF` | |
| Status Live/Success | `SuccessSoft` nền, `Success` chữ | | |
| Status Warning | `WarningSoft` nền, `Warning` chữ | | Điểm nhấn ấm |
| Status Danger | `DangerSoft` nền, `Danger` chữ | | |
| Status Đang chạy | `InfoSoft` nền, `Info` chữ | | |

---

## 4. Typography

```
Font chính:      Segoe UI, 9pt       — mọi label, input, button
Font bold:       Segoe UI Semibold   — heading, section title, nút
Font mono:       Consolas, 9.5pt     — UID, token, link, ID
Font stat badge: Segoe UI Semibold  — số liệu thống kê

Không dùng font khác. Không dùng italic. Không dùng underline làm decoration.
```

### Type scale

| Mục | Font | Size | Weight | Màu |
|---|---|---|---|---|
| Window title | UiFontBold | 10pt | Semibold | Text |
| Section header | UiFontBold | 9pt | Semibold | Text |
| Field label | UiFont | 9pt | Regular | TextSub |
| Body text | UiFont | 9pt | Regular | Text |
| Mono data | MonoFont | 9.5pt | Regular | Text |
| Stat number | UiFontBold | 9pt | Semibold | Accent |

---

## 5. Component Specs

### 5.1 Button (RoundedButton)

```
Width:    110px mặc định, có thể override
Height:   34px
Radius:   8px
Shadow:   Drop shadow 2px, blur 4px, alpha 25%
Hover:    Sáng hơn 1 bậc, lift 1px
Pressed:  Đen hơn 1 bậc, shift 1px xuống
Disabled: Gray-400 (#9CA3AF), không shadow

3 loại:
  Primary   → Accent / AccentHover
  Danger    → Danger / hover: #EF4444
  Secondary → Panel / border: Border / text: Text / hover: SurfaceRow
```

### 5.2 Input (TextBox / NumericUpDown)

```
Height:   26px
Border:   1px solid Border
Radius:   0px — không bo (tool nghiệp vụ nên góc vuông)
Bg:       Panel
Focus:    border → Accent, 2px
Padding:  H 8px, V 4px
Placeholder: TextSub, italic
NumericUpDown: text-align right, width 90px
```

### 5.3 DataGridView (Profile Grid + Log Grid)

```
Row height:     28px
Header height:  32px
Header bg:      SurfaceDark (#1E293B)
Header text:    White, Semibold
Cell padding:   6px left, 3px top/bottom
Grid lines:     0.5px Divider, chỉ horizontal
Selection:      Accent bg / White text
Alt row:        SurfaceRow
No row header
Column header sort glyph: Lệch 4px từ text
```

#### Profile Grid — cột

| Cột | Key | Width | Ghi chú |
|---|---|---|---|
| ☐ | Checked | 44px | Checkbox header (check all) |
| STT | Index | 50px | Center |
| UID | Uid | 150px | MonoFont |
| Token | Token | Masked 4+***+4 | MonoFont |
| Trạng thái | Status | 140px | Colored badge |
| Tác vụ | Tasks | 70px | |
| Lỗi gần nhất | Error | Auto | Wrapped, màu=status |

#### Log Grid — cột

| Cột | Key | Width | Ghi chú |
|---|---|---|---|
| STT | Index | 50px | Center |
| UID | Uid | 140px | MonoFont |
| Link | Link | Auto (fill) | Wrapped, truncated |
| Hành động | Action | 90px | |
| Proxy | Proxy | 160px | |
| Trạng thái | Status | 130px | Colored |
| Lỗi | Error | Auto | Màu=status |

### 5.4 Tab Control (FlatTabControl)

```
Tab height:    38px
Tab min width: 100px
Selected tab:
  bg:    #FFFFFF (Panel)
  border-bottom: 3px Accent
  text:  Accent, Semibold
Unselected:
  bg:    TabBack
  text:  TextSub
  border: none
Strip (background phía sau tabs): AppBack

Indicator bar: mỗi tab có top border 3px màu Accent khi selected
```

### 5.5 Section Header Eyebrow

```
Layout:  [🔵 6px vertical bar] [Label text:]
Bar màu: Accent
Label:   UiFontBold, 9pt, Text
Margin:  bottom 8px
```

### 5.6 Stats Bar (log bar)

```
Bg:       SurfaceDark (#1E293B)
Text:     White
Padding:  10px all sides
Layout:   "Tổng: N | Đã chạy: N | Thành công: N | Thất bại: N | Đang chờ proxy: N"
Mỗi số có màu tương ứng status: Accent, Success, Danger, Info
```

### 5.7 Status Badge (inline trong cell)

```
Không dùng rounded pill — dùng flat tag:
  Padding: 3px 8px
  Border-left: 3px solid [status-color]
  Bg: [status-soft-color]
  Text: [status-color], UiFontBold 8pt
```

---

## 6. Layout & Spacing

### Spacing scale (tất cả padding/margin/gap dùng giá trị này)

```
4px   — tight (icon + text, checkbox + label)
8px   — default input padding
12px  — panel padding, section gap
16px  — card padding, grid padding
20px  — tab content padding
24px  — major section break
```

### Tab Layout

**Hồ sơ (Profile):**
```
┌─────────────────────────────────────────────┐
│ [Cập nhật] [Lưu dữ liệu] [Xóa đã chọn]     │  ← action bar top-right
├─────────────────────────────────────────────┤
│ ☐ │ STT │ UID │ Token │ Trạng thái │ Tac vu │ Loi │
│ ☐ │  1  │ ... │  ...  │    Live    │   2    │ -   │
│ ☐ │  2  │ ... │  ...  │   Token out│   0    │ ... │
│ ...                                         │
├─────────────────────────────────────────────┤
│ Tổng: 2 │ Tích chọn: 1 │ Trạng thái: 1/2   │  ← summary bar
└─────────────────────────────────────────────┘
```

**Tương tác (Interaction):**
```
┌──────────────────────────────────────────────────────┐
│ [Chỉnh sửa] [Xóa] [Comment mới]         ← action tabs│
├──────────────────────────────────────────────────────┤
│ Số luồng: [5]              [Bắt đầu] [Dừng]          │
│ ┌─ UID profile ──────────┬─ Link comment ──────────┐ │
│ │ (để trống = tự check)  │ Mỗi dòng 1 link          │ │
│ │                         │                          │ │
│ └─────────────────────────┴──────────────────────────┘ │
│ Nội dung mới: [Ẩn]                                   │
│ ┌ multiline input ────────────────────────────────┐  │
│ └──────────────────────────────────────────────────┘  │
│ File ảnh: [/path]            [Chọn file] [Lưu dữ liệu│
│ Mỗi UID cmt: [5] post                                │
│ Delay từ: [0] đến: [0] sau mỗi vòng: [1]             │
├──────────────────────────────────────────────────────┤
│ Tổng: 0 | Đã chạy: 0 | Thành công: 0 | ...         │  ← dark stats bar
├──────────────────────────────────────────────────────┤
│ Grid log (fill remaining space)                      │
│ STT │ UID │ Link │ Action │ Proxy │ Status │ Error   │
└──────────────────────────────────────────────────────┘
```

**Proxy (Proxy):**
```
┌──────────────────────────────────────────────┐
│ Token Kiot: [••••••]    Lượt mỗi IP: [4]    │
│ API key proxy:                                │
│ ┌ multiline input ──────────────────────────┐ │
│ └───────────────────────────────────────────┘ │
│ URL lấy IP mới: [https://...]                │
│ URL IP hiện tại: [https://...]               │
│ Kiểm tra mỗi (giây): [5]                     │
│                                              │
│ [Lưu cấu hình] [Bắt đầu proxy] [Dừng] [Xóa] │
├──────────────────────────────────────────────┤
│ STT │ Key │ Proxy │ Remaining │ Status │ ... │
│ ... grid proxy ...                           │
└──────────────────────────────────────────────┘
```

---

## 7. Interaction & Motion

| Moment | Hiệu ứng | Chi tiết |
|---|---|---|
| Button hover | Lift 1px + shadow tăng | 120ms ease-out |
| Button press | Shift 1px xuống + màu đậm | 80ms |
| Grid row hover | Highlight trắng nhạt | 0ms — instant |
| Tab switch | Fade 120ms | Mềm, không jump |
| Checkbox toggle | Instant | Không animation |
| Save thành công | Fade-in toast bottom-right | 2s rồi fade out |

> Không có page-load animation, không có scroll-trigger, không có parallax — đây là desktop tool không phải landing page.

---

## 8. Dark Mode

```
KHÔNG có dark mode trong scope hiện tại.
Palette được tối ưu cho light mode — contrast ratio đạt WCAG AA trên nền sáng.
Nếu sau này cần dark mode, sẽ làm ở một lần refactor riêng.
```

---

## 9. Iconography

```
KHÔNG dùng icon library.
Dùng text-only cho tất cả control.
Reason: WinForms icon support hạn chế, thêm icon font/library bloat file size.
Status indicator: dùng color-coded left border (3px) trên grid row.
```

---

## 10. Responsive (WinForms — Minimum Size)

```
MinimumSize: 1180 × 720
Không responsive như web — app fix size trên desktop.
User có thể resize nhưng minimum đảm bảo grid không vỡ layout.
```

---

## 11. tờ trắng (Placeholder / Empty States)

**Profile grid rỗng:**
```
Hiện text ở grid center:
  "Nhấn chuột phải → Nhập dữ liệu để bắt đầu"
  Màu: TextSub, italic
```

**Log grid chưa chạy:**
```
Grid trống, không có message — tiêu đề cột đủ nói rõ đây là log.
```

---

## 12. Accessibility (WinForms limits)

| Yếu tố | Xử lý |
|---|---|
| Focus ring | TextBox tự có underline khi focus → giữ nguyên |
| Button focus | `TabStop` = true, dùng `Paint` vẽ focus rectangle 2px |
| Color contrast | Text #0F172A trên #F8FAFC = 15:1 ✓ WCAG AAA |
| Accent contrast | White trên #2563EB = 4.6:1 ✓ WCAG AA |
| Error message | Luôn có icon MessageBox + text — không chỉ màu đỏ |

---

## 13. Files cần đọc khi implement

| File | Vai trò |
|---|---|
| `Form1.cs` | UI code chính — builder pattern các tab |
| `Form1.Designer.cs` | Auto-generated controls (không edit trực tiếp) |
| `RoundedButton.cs` | Custom button renderer |
| `FlatTabControl.cs` | Custom tab strip |
| `ThemeConstants.cs` | **Đọc file này trước khi code giao diện** — palette + font |
| `GridThemer.cs` | Grid styling helper |

---

## 14. Quick Reference — khi code giao diện

```csharp
// Nền chính
this.BackColor = ThemeConstants.AppBack;

// Panel/card
panel.BackColor = ThemeConstants.Panel;

// Button chính
var btn = new RoundedButton {
    Text = "Bắt đầu",
    Width = 110, Height = 34,
    ButtonColor = ThemeConstants.Accent,
    ButtonHoverColor = ThemeConstants.AccentHover,
    ButtonPressedColor = ThemeConstants.PrimaryDark,
    BackColor = ThemeConstants.Accent,
    ForeColor = Color.White
};

// Text input
input.BorderStyle = BorderStyle.FixedSingle;
input.BackColor = ThemeConstants.Panel;
input.ForeColor = ThemeConstants.Text;

// Grid — gọi 1 lần
GridThemer.ApplyBase(myGrid);

// Section eyebrow
var eyebrow = new Panel { Height = 20, BackColor = ThemeConstants.Accent, Dock = DockStyle.Left, Width = 4 };
var label = new Label { Text = "Tiêu đề", Font = ThemeConstants.UiFontBold, Dock = DockStyle.Fill };
```

---

## 15. Design Decisions Log

| # | Quyết định | Lý do |
|---|---|---|
| 1 | Accent xanh electric (#2563EB) thay vì royal blue cũ | Tương phản cao hơn trên white, cảm giác công nghệ hơn |
| 2 | Grid header màu tối (#1E293B) | Tạo depth, rõ ranh giới data area |
| 3 | Warning màu amber (duy nhất có sắc ấm) | "Precision Instrument" — chỉ amber là ngoại lệ, dùng cho cảnh báo |
| 4 | Không rounded trên input | Tool nghiệp vụ → góc vuông = rõ ràng, chính xác |
| 5 | Status qua cell color + left border | Không cần icon, color-blind friendly (shape + color) |
| 6 | Không dark mode | Scope gọn, light mode đủ tốt cho use case này |
