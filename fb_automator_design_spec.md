# Thiết kế UI/UX & Tech Stack: FB Automator (Web/Desktop Dashboard)

Tài liệu này mô tả chi tiết thiết kế giao diện, trải nghiệm người dùng (UI/UX) và các công nghệ sử dụng để xây dựng ứng dụng tự động hóa Facebook mang tên **FB Automator**.

---

## 1. Phong cách Thiết kế (Design Guidelines)

*   **Định hướng:** Modern SaaS dashboard, Professional enterprise software.
*   **Cảm hứng:** Linear, Notion, Stripe Dashboard, Ant Design Pro.
*   **Màu sắc:**
    *   **Nền (Background):** Trắng (Clean minimal interface).
    *   **Màu chủ đạo (Primary):** Xanh dương (`#2563EB`).
    *   **Đường viền (Borders):** Xám nhạt (`#E5E7EB`).
    *   **Sidebar:** Nền tối (`#1F2937`).
*   **Typography:** Font chữ `Inter`.
*   **Hình khối & Khoảng cách:**
    *   Hệ thống lưới (Grid system): `8px`.
    *   Bo góc tổng thể (Rounded corners): `10-12px`.
    *   Bo góc Thẻ (Cards): `12px`.
    *   Bo góc Nút bấm (Buttons): `8px`.
*   **Hiệu ứng (Effects):** Soft shadows cho các thẻ, Hiệu ứng chuyển động mượt mà (Smooth animations 200ms) khi hover.

---

## 2. Công nghệ Giao diện (Tech Stack)

Để đảm bảo chất lượng giao diện chuẩn Figma (giống 100%), hệ thống sử dụng:
*   **Core:** React, Next.js (App Router), TypeScript.
*   **Styling:** TailwindCSS.
*   **UI Components:** shadcn/ui.
*   **Icons:** Lucide Icons.
*   **Data Table:** TanStack Table.
*   **Form Management:** React Hook Form.
*   **Animations:** Framer Motion.

---

## 3. Cấu trúc Bố cục (Global Layout)

Giao diện được thiết kế tối ưu cho độ phân giải màn hình Desktop (`1600x900`).

### 3.1. Left Sidebar (Thanh Điều Hướng Trái)
*   **Nền:** Tối (`#1F2937`), Chiều rộng cố định: `~250px`.
*   **Top (Header):** Logo và dòng chữ "FB Automator - Professional Suite".
*   **Menu Items (Kèm Lucide Icons):**
    *   Quản lý Profile
    *   Auto Comment
    *   Auto Đăng Bài
    *   Auto Share Nhóm
    *   Quản lý Proxy & Cấu hình
    *   *Trạng thái Active:* Nền xanh dương (`#2563EB`), Icon màu trắng, bo góc.
*   **Bottom (Footer):** Hiển thị Avatar người dùng, Username, Vai trò (Role) và Trạng thái hệ thống (System status).

### 3.2. Top Navigation (Thanh Điều Hướng Trên)
*   **Bố cục:** Nằm ngang (Horizontal top bar).
*   **Left:** Thanh tìm kiếm chung (Search box) với Placeholder: *"Tìm kiếm tác vụ..."*
*   **Center:** Các Tab chuyển đổi hiển thị: `System Health`, `Tasks`, `Logs`.
*   **Right:**
    *   Nút **Start All** (Màu xanh dương `#2563EB`).
    *   Nút **Stop All** (Màu xám).
    *   Icon Thông báo (Notification).
    *   Icon Cài đặt (Settings).

---

## 4. Chi tiết Các Trang Giao Diện (Pages)

### PAGE 1: Quản lý Profile Facebook
Trang tổng quan để quản lý và đồng bộ các tài khoản Facebook tự động.

*   **Header:**
    *   **Title:** Quản lý Profile Facebook
    *   **Subtitle:** Quản lý và đồng bộ các tài khoản Facebook tự động.
    *   **Hành động (Phải):** Nút "Nhập Profile (UID|Token)" và Nút Primary "Đồng bộ dữ liệu".
*   **Thống Kê (Statistics Cards - 4 Cột):**
    *   *Card 1 (Icon Users):* TỔNG PROFILE (VD: 1,284) | Biến động: +12 trong 24 giờ.
    *   *Card 2 (Green check icon):* ĐANG HOẠT ĐỘNG (VD: 1,240) | Tỷ lệ: 96.5%.
    *   *Card 3 (Red warning icon):* LỖI CHECKPOINT (VD: 44) | Ghi chú: Cần xử lý.
    *   *Card 4 (Blue shield):* PROXY ONLINE (VD: 98%).
*   **Bảng Dữ Liệu (Data Table):**
    *   **Thiết kế:** Modern hover state, Sticky header.
    *   **Cột:** Checkbox | UID | Tên Profile | Fanpage | Nhóm | Trạng thái (Live xanh, Checkpoint đỏ, Offline xám) | Proxy | Actions.
    *   **Footer:** Phân trang (Pagination) ở góc dưới bên phải.

### PAGE 2: Auto Đăng Bài
Thiết kế theo bố cục chia 2 cột (Two-column layout).

*   **Cột Trái (Left panel) - Card "Cấu hình bài đăng":**
    *   **Nơi đăng (Checkboxes):** Đăng lên cá nhân, Fanpage.
    *   **Nội dung (Textarea):** Ô nhập văn bản (Placeholder: *Nhập nội dung bài đăng...*), có kèm bộ đếm ký tự (Character counter).
    *   **Media Upload:** Khu vực tải ảnh/video thiết kế to bản, viền đứt quãng (Dashed box), Icon Cloud upload và dòng chữ *"Kéo thả hoặc tải lên ảnh/video"*.
    *   **Cấu hình chạy:** Ô nhập Số luồng (Thread count), Ô nhập Thời gian trễ (Delay).
    *   **Footer Buttons:** Nút "Bắt đầu chiến dịch" (Xanh dương) và "Lưu cấu hình" (Xám).
*   **Cột Phải (Right panel) - Danh sách mục tiêu:**
    *   **Header:** Ô tìm kiếm Profile/Page.
    *   **Danh sách (Profile Cards):** Hiển thị Avatar, Tên Profile, UID, Badge trạng thái (Status badge), và Checkbox chọn lựa.
    *   **Footer Summary:** Hiển thị tổng số lượng đang được chọn (VD: *Đã chọn: 1 profile*).

### PAGE 3: Auto Share Nhóm
Trang hiện tại ở trạng thái trống (Empty state page) dùng để thêm chiến dịch mới.

*   **Bố cục:** Canh giữa màn hình (Center alignment).
*   **Thành phần:**
    *   Một hình minh họa lớn (Large illustration).
    *   **Title:** Auto Share Nhóm.
    *   **Description:** Chọn nhóm Facebook để bắt đầu chiến dịch chia sẻ tự động.
    *   **Call to action:** Nút màu xanh dương "Thêm chiến dịch".

---
*Lưu ý: Yêu cầu áp dụng chặt chẽ kiến trúc React Component và Tailwind utility classes để đảm bảo code sạch, gọn và giao diện responsive như mong muốn.*
