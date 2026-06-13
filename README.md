# Comment Edit Delete

Desktop WinForms tool for managing Facebook comment tasks with profiles, token checking, edit/delete/new comment actions, and KiotProxy rotation.

Công cụ WinForms desktop để quản lý tác vụ comment Facebook: quản lý profile, check token, chỉnh sửa/xóa/comment mới và xoay proxy KiotProxy.

---

## English

### Requirements

- Windows
- .NET SDK 9.0
- Valid Facebook tokens owned by the user
- Tokens must have the required permissions for the target comments/posts
- KiotProxy API keys if proxy mode is used

### Run

```powershell
dotnet run
```

Build Debug:

```powershell
dotnet build -c Debug
```

Executable:

```text
bin\Debug\net9.0-windows\ToolEditDeleteCmt.exe
```

### Profile Tab

Input format, one profile per line:

```text
uid|token
```

Features:

- `Import .txt`: import profile list from a text file.
- `Load profile`: load/merge profiles. Duplicate UID refreshes the token instead of adding a new row.
- `Check token`: check token live/die/checkpoint using Graph API `/me`.
- `Save data`: save profiles and current state.
- `Delete checked`: delete checked profiles.
- `Clear`: clear all loaded profiles.

The profile table shows:

- Index
- UID
- Full token
- Token status
- Task count
- Last error

Status colors:

- `Live`: green
- `Token out`: yellow
- `Checkpoint` / `Die`: red

Profile status is saved by UID. If a token becomes checkpointed while running, the state is preserved after reopening the app.

### Interaction Tab

Main inputs:

- `UID profile`: leave empty for Graph auto-check, or enter UIDs manually.
- `Comment link`: used for edit/delete.
- `Post ID/link`: used for new comments.

Each input box has a live counter for non-empty lines.

Supported actions:

- Edit comment
- Delete comment
- New comment

#### Edit/Delete Comment

- Enter comment links or comment IDs in `Comment link`.
- If UID input is empty, the tool uses the first profile token to resolve comment author UID through Graph API, then maps that UID to the matching token in the Profile tab.
- If one UID is entered, it applies to all comment links.
- If multiple UIDs are entered, UID line count must match comment link line count.

#### New Comment

- `Comment link` is not required.
- Enter post IDs or post links in `Post ID/link`.
- If UID input is empty, all loaded profiles are used.
- `Posts per UID` limits how many posts each UID can comment on.
- Example: 3 profiles, 50 posts, `Posts per UID = 5` creates only 15 tasks.
- Successful comments return links in this format:

```text
https://www.facebook.com/{postId}?comment_id={commentId}
```

#### Threads And Rounds

`Thread count` controls how many tasks run in one round.

Example with `Thread count = 5`:

- The tool creates 5 log rows for the current round.
- The next round starts only after those 5 rows finish.
- If delay is enabled, it applies after each completed round.

#### Text And Images

- `New content`: supports multiple content blocks. Separate blocks with one blank line.
- The tool randomly picks one content block for each task.
- `Choose file`: select one or more image files.
- The image list can be edited manually, one file per line.
- When image is provided, the tool sends multipart `source` for edit/new comment requests.

### Proxy Tab

KiotProxy support.

Inputs:

- `Kiot token`: KiotProxy auth token.
- `Proxy API key`: one API key per line.
- `Uses per IP`: how many tasks can use each IP.

Default endpoints:

```text
https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}
https://api.kiotproxy.com/api/v1/proxies/current?key={apiKey}
```

Proxy behavior:

- If proxy is not started, tasks run direct.
- If proxy is started, tasks must wait for a Ready proxy and never fall back to local IP.
- Ready proxies are assigned by round-robin: A -> B -> C -> A -> B -> C.
- Each task consumes one proxy use.
- When a proxy reaches zero uses, it changes to `Refreshing` and gets a new IP.
- Refreshing/waiting proxies are skipped until Ready again.

### Logs And Popups

- One log row per task.
- Task status updates on the same row.
- A summary popup appears after all interaction tasks finish.
- If the user clicks Stop, the finished popup is not shown.
- On app exit, a confirmation popup appears. If tasks/proxy are running, it warns that current work will be stopped.

### Saved Data

Settings are saved here:

```text
%LOCALAPPDATA%\ToolEditDeleteCmt\settings.dpapi
```

Windows DPAPI `CurrentUser` is used to protect the settings file.

Saved data includes:

- Profiles `uid|token`
- Profile status
- UID/comment/post inputs
- Comment content
- Image file list
- Proxy configuration
- KiotProxy token/API keys

### Facebook API

The tool uses Facebook Graph API:

- Edit comment: `POST /{commentId}`
- Delete comment: `DELETE /{commentId}`
- New comment: `POST /{postId}/comments`
- Check token: `GET /me?fields=id`

The tool does not bypass captcha, does not extract tokens from browsers, does not scrape, and does not bypass platform limits. Users are responsible for using valid tokens with proper permissions.

### Publish

```powershell
dotnet publish -c Release -r win-x64 --self-contained true
```

Output:

```text
bin\Release\net9.0-windows\win-x64\publish
```

---

## Offline License / License Offline

FlowMeta uses an offline machine-bound license:

- The app shows a `MachineID` when the user has no valid license.
- The user sends that `MachineID` to the owner/admin.
- The owner generates a license key with an expiry date.
- The user pastes the license key into the app.
- The license is saved locally with Windows DPAPI at:

```text
%LOCALAPPDATA%\FlowMeta\license.dpapi
```

Generate a license key:

Build/open the standalone admin app:

```powershell
dotnet build .\FlowMetaLicenseAdmin\FlowMetaLicenseAdmin.csproj -c Release
```

Admin app output:

```text
FlowMetaLicenseAdmin\bin\Release\net9.0-windows\FlowMetaLicenseAdmin.exe
```

The standalone admin app reads `license-private.key` from file. Keep that key private and do not ship it with the customer app.

Open the admin form:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\FlowMetaLicenseAdmin.ps1
```

Or generate from command line:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\Create-FlowMetaLicense.ps1 -MachineId "FM-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX" -Expires "2026-12-31 23:59:59"
```

Important:

- Keep `license-private.key` private.
- Do not send or commit `license-private.key`.
- If `license-private.key` is lost or regenerated, old app builds will not accept newly generated keys unless the app public key is updated and rebuilt.

## GitHub Release Update Check

```text
    ________               __  ___     __
   / ____/ /___ _      __ /  |/  /__  / /_____ _
  / /_  / / __ \ | /| / // /|_/ / _ \/ __/ __ `/
 / __/ / / /_/ / |/ |/ // /  / /  __/ /_/ /_/ /
/_/   /_/\____/|__/|__//_/  /_/\___/\__/\__,_/

        [ RELEASE ]  FlowMeta.exe
        [ UPDATE  ]  GitHub Release
        [ STATUS  ]  Latest build only
```

FlowMeta sử dụng license offline gắn theo máy:

- App hiển thị `MachineID` nếu chưa có license hợp lệ.
- Người dùng gửi `MachineID` cho admin.
- Admin tạo license key kèm ngày hết hạn.
- Người dùng dán license key vào app.
- License được lưu mã hóa bằng Windows DPAPI tại:

```text
%LOCALAPPDATA%\FlowMeta\license.dpapi
```

Lệnh tạo license:

Build/mở app admin riêng:

```powershell
dotnet build .\FlowMetaLicenseAdmin\FlowMetaLicenseAdmin.csproj -c Release
```

File app admin:

```text
FlowMetaLicenseAdmin\bin\Release\net9.0-windows\FlowMetaLicenseAdmin.exe
```

App admin đọc `license-private.key` từ file. Giữ kín private key và không gửi cùng app khách.

Mở form admin:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\FlowMetaLicenseAdmin.ps1
```

Hoặc tạo bằng lệnh:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\Create-FlowMetaLicense.ps1 -MachineId "FM-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX" -Expires "2026-12-31 23:59:59"
```

Lưu ý:

- Giữ kín file `license-private.key`.
- Không gửi hoặc commit `license-private.key`.
- Nếu mất hoặc tạo lại `license-private.key`, các bản app cũ sẽ không nhận key mới trừ khi cập nhật public key trong app và build lại.

## Kiểm Tra Cập Nhật Qua GitHub Release

```text
    ________               __  ___     __
   / ____/ /___ _      __ /  |/  /__  / /_____ _
  / /_  / / __ \ | /| / // /|_/ / _ \/ __/ __ `/
 / __/ / / /_/ / |/ |/ // /  / /  __/ /_/ /_/ /
/_/   /_/\____/|__/|__//_/  /_/\___/\__/\__,_/

        [ PHÁT HÀNH ]  FlowMeta.exe
        [ CẬP NHẬT  ]  GitHub Release
        [ TRẠNG THÁI]  Chỉ giữ bản mới nhất
```

---

## Tiếng Việt

### Yêu Cầu

- Windows
- .NET SDK 9.0
- Token Facebook hợp lệ do người dùng sở hữu
- Token phải có quyền thao tác với comment/bài viết mục tiêu
- API key KiotProxy nếu muốn chạy qua proxy

### Chạy Tool

```powershell
dotnet run
```

Build Debug:

```powershell
dotnet build -c Debug
```

File chạy:

```text
bin\Debug\net9.0-windows\ToolEditDeleteCmt.exe
```

### Tab Hồ Sơ

Định dạng nhập, mỗi dòng một profile:

```text
uid|token
```

Chức năng:

- `Nhập .txt`: nhập danh sách profile từ file text.
- `Nạp profile`: nạp/merge profile. UID trùng thì refresh token, không thêm dòng mới.
- `Check token`: kiểm tra token live/die/checkpoint bằng Graph API `/me`.
- `Lưu dữ liệu`: lưu profile và trạng thái hiện tại.
- `Xóa đã tích`: xóa các profile được tick.
- `Xóa trắng`: xóa toàn bộ profile đã nạp.

Bảng profile hiển thị:

- STT
- UID
- Token đầy đủ
- Trạng thái token
- Số tác vụ
- Lỗi gần nhất

Màu trạng thái:

- `Live`: xanh
- `Token out`: vàng
- `Checkpoint` / `Die`: đỏ

Trạng thái profile được lưu theo UID. Nếu token bị checkpoint trong lúc chạy, mở lại tool vẫn giữ trạng thái đó.

### Tab Tương Tác

Các ô nhập chính:

- `UID profile`: để trống để tool tự check bằng Graph, hoặc nhập UID thủ công.
- `Link comment`: dùng cho chỉnh sửa/xóa comment.
- `ID/link bài viết`: dùng cho comment mới.

Mỗi ô có bộ đếm số dòng không rỗng.

Hành động hỗ trợ:

- Chỉnh sửa comment
- Xóa comment
- Comment mới

#### Chỉnh Sửa/Xóa Comment

- Nhập link comment hoặc comment ID vào ô `Link comment`.
- Nếu ô UID trống, tool dùng token đầu tiên để lấy UID tác giả comment bằng Graph API, sau đó tìm token khớp UID trong tab Hồ sơ.
- Nếu nhập 1 UID, UID đó áp dụng cho toàn bộ link.
- Nếu nhập nhiều UID, số dòng UID phải bằng số dòng link.

#### Comment Mới

- Không cần nhập `Link comment`.
- Nhập danh sách post ID hoặc link post vào ô `ID/link bài viết`.
- Nếu UID trống, tool dùng toàn bộ profile đang nạp.
- `Mỗi UID cmt`: giới hạn mỗi UID comment bao nhiêu post.
- Ví dụ có 3 profile, 50 post, nhập `Mỗi UID cmt = 5` thì chỉ tạo 15 task.
- Comment thành công trả link dạng:

```text
https://www.facebook.com/{postId}?comment_id={commentId}
```

#### Số Luồng Và Vòng Chạy

`Số luồng` quyết định số task chạy trong một vòng.

Ví dụ `Số luồng = 5`:

- Tool tạo 5 dòng log cho vòng hiện tại.
- Chạy xong 5 dòng đó mới sang vòng tiếp theo.
- Nếu bật delay, delay được áp dụng sau mỗi vòng hoàn tất.

#### Nội Dung Và Ảnh

- `Nội dung mới`: có thể nhập nhiều nội dung. Mỗi block cách nhau bằng một dòng trống.
- Tool chọn ngẫu nhiên một nội dung cho mỗi task.
- `Chọn file`: chọn một hoặc nhiều file ảnh.
- Có thể sửa tay danh sách file ảnh, mỗi file một dòng.
- Khi có ảnh, tool gửi multipart `source` cho request edit/comment mới.

### Tab Proxy

Hỗ trợ KiotProxy.

Nhập:

- `Token Kiot`: auth token KiotProxy.
- `API key proxy`: mỗi dòng một API key.
- `Lượt mỗi IP`: số task được dùng trên mỗi IP.

Endpoint mặc định:

```text
https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}
https://api.kiotproxy.com/api/v1/proxies/current?key={apiKey}
```

Logic proxy:

- Nếu không bật proxy, task chạy direct.
- Nếu đã bật proxy, task bắt buộc chờ proxy Ready, không tự fallback về IP máy.
- Proxy được cấp theo vòng tròn: A -> B -> C -> A -> B -> C.
- Mỗi task trừ một lượt proxy.
- Hết lượt thì proxy chuyển `Refreshing` và tự get IP mới.
- Proxy đang refresh/waiting sẽ bị bỏ qua cho đến khi Ready lại.

### Log Và Popup

- Mỗi task có một dòng log.
- Trạng thái task cập nhật trên đúng dòng đó.
- Chạy xong hiện popup tổng kết.
- Nếu người dùng bấm Dừng, popup hoàn tất không hiện.
- Khi thoát app sẽ có popup xác nhận. Nếu task/proxy đang chạy, popup báo rõ thoát sẽ dừng tác vụ hiện tại.

### Lưu Dữ Liệu

Dữ liệu được lưu tại:

```text
%LOCALAPPDATA%\ToolEditDeleteCmt\settings.dpapi
```

Tool dùng Windows DPAPI `CurrentUser` để bảo vệ file cấu hình.

Dữ liệu được lưu:

- Profile `uid|token`
- Trạng thái profile
- UID/link/post input
- Nội dung comment
- Danh sách file ảnh
- Cấu hình proxy
- Token/API key KiotProxy

### API Facebook

Tool dùng Facebook Graph API:

- Edit comment: `POST /{commentId}`
- Delete comment: `DELETE /{commentId}`
- Comment mới: `POST /{postId}/comments`
- Check token: `GET /me?fields=id`

Tool không bypass captcha, không lấy token từ trình duyệt, không scraping và không vượt giới hạn nền tảng. Người dùng chịu trách nhiệm sử dụng token hợp lệ và có quyền phù hợp.

### Publish

```powershell
dotnet publish -c Release -r win-x64 --self-contained true
```

Output:

```text
bin\Release\net9.0-windows\win-x64\publish
```
