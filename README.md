# Comment Edit Delete

Tool WinForms C# để quản lý profile `uid|token`, kiểm tra token, comment mới, chỉnh sửa comment, xóa comment và xoay proxy KiotProxy.

## Yêu Cầu

- Windows
- .NET SDK 9.0
- Token Facebook hợp lệ do người dùng sở hữu và có quyền thao tác với comment/bài viết
- API key KiotProxy nếu muốn chạy qua proxy

## Chạy Tool

```powershell
dotnet run
```

Build Debug:

```powershell
dotnet build -c Debug
```

File chạy sau khi build:

```text
bin\Debug\net9.0-windows\ToolEditDeleteCmt.exe
```

## Tab Hồ Sơ

Nhập mỗi dòng một profile:

```text
uid|token
```

Chức năng:

- `Nhập .txt`: nhập danh sách profile từ file text.
- `Nạp profile`: nạp thêm profile vào bảng. Nếu trùng UID thì chỉ refresh token của UID đó.
- `Check token`: kiểm tra token live/die/checkpoint bằng Graph API `/me`.
- `Lưu dữ liệu`: lưu profile và trạng thái hiện tại.
- `Xóa đã tích`: xóa các profile được tick.
- `Xóa trắng`: xóa toàn bộ profile đang nạp.

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
- `Checkpoint` hoặc `Die`: đỏ

Trạng thái profile được lưu lại theo UID. Nếu token bị checkpoint khi đang chạy, mở lại tool vẫn giữ trạng thái đó.

## Tab Tương Tác

Các ô nhập chính:

- `UID profile`: để trống để tool tự lấy UID comment bằng Graph, hoặc nhập UID thủ công.
- `Link comment`: dùng cho chỉnh sửa/xóa comment.
- `ID/link bài viết`: dùng cho comment mới.

Mỗi ô có bộ đếm số dòng không rỗng để dễ kiểm tra dữ liệu đầu vào.

Hành động hỗ trợ:

- `Chỉnh sửa comment`
- `Xóa comment`
- `Comment mới`

### Chỉnh Sửa/Xóa Comment

- Nhập link comment hoặc comment ID vào ô `Link comment`.
- Nếu ô UID trống, tool dùng token đầu tiên để check UID tác giả comment bằng Graph API rồi gán đúng token theo UID trong tab Hồ sơ.
- Nếu nhập 1 UID, UID đó áp dụng cho toàn bộ link.
- Nếu nhập nhiều UID, số dòng UID phải bằng số dòng link.

### Comment Mới

- Không cần nhập `Link comment`.
- Nhập danh sách post ID hoặc link post vào ô `ID/link bài viết`.
- Nếu UID trống, tool dùng toàn bộ profile đang nạp.
- `Mỗi UID cmt`: giới hạn mỗi UID comment bao nhiêu post.
- Ví dụ có 3 profile, 50 post, nhập `Mỗi UID cmt = 5` thì tool chỉ tạo 15 task rồi dừng.
- Comment thành công trả link dạng:

```text
https://www.facebook.com/{postId}?comment_id={commentId}
```

### Số Luồng Và Vòng Chạy

`Số luồng` quyết định số task chạy trong một vòng.

Ví dụ `Số luồng = 5`:

- Tool tạo 5 dòng log cho vòng hiện tại.
- Chạy xong 5 dòng đó mới qua vòng tiếp theo.
- Nếu có delay sau mỗi vòng, delay được áp dụng sau khi vòng hoàn tất.

### Nội Dung Và Ảnh

- `Nội dung mới`: có thể nhập nhiều nội dung. Mỗi block cách nhau bằng một dòng trống.
- Tool chọn ngẫu nhiên một nội dung cho mỗi task.
- `Chọn file`: chọn một hoặc nhiều file ảnh.
- Có thể sửa tay danh sách file ảnh, mỗi file một dòng.
- Khi edit/comment có ảnh, tool gửi ảnh dạng multipart `source`.

## Tab Proxy

Hỗ trợ KiotProxy.

Nhập:

- `Token Kiot`: auth token KiotProxy.
- `API key proxy`: mỗi dòng một API key get IP.
- `Lượt mỗi IP`: số task được dùng trên mỗi IP.

Endpoint mặc định:

```text
https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}
https://api.kiotproxy.com/api/v1/proxies/current?key={apiKey}
```

Logic proxy:

- Nếu không bật proxy, task chạy direct.
- Nếu đã bật proxy, task bắt buộc chờ proxy Ready, không tự fallback về IP máy.
- Proxy được cấp theo round-robin: A -> B -> C -> A -> B -> C.
- Mỗi task dùng một lượt proxy.
- Hết lượt thì proxy chuyển `Refreshing` và tự get IP mới.
- Proxy đang refresh/waiting sẽ bị bỏ qua khỏi vòng xoay cho đến khi Ready lại.

## Log Và Popup

- Log chỉ có một dòng cho mỗi task.
- Trạng thái task được cập nhật trên đúng dòng đó.
- Chạy xong tự hiện popup tổng kết.
- Nếu người dùng bấm `Dừng`, tool không hiện popup hoàn tất.
- Khi thoát app, tool hiện popup xác nhận. Nếu task/proxy đang chạy, popup sẽ báo rõ là thoát sẽ dừng tác vụ hiện tại.

## Lưu Dữ Liệu

Dữ liệu được lưu tại:

```text
%LOCALAPPDATA%\ToolEditDeleteCmt\settings.dpapi
```

Tool dùng Windows DPAPI theo user hiện tại để bảo vệ file cấu hình.

Dữ liệu được lưu:

- Profile `uid|token`
- Trạng thái profile
- UID/link/post input
- Nội dung comment
- File ảnh
- Cấu hình proxy
- Token/API key KiotProxy

## API Facebook

Tool dùng Facebook Graph API:

- Edit comment: `POST /{commentId}`
- Delete comment: `DELETE /{commentId}`
- Comment mới: `POST /{postId}/comments`
- Check token: `GET /me?fields=id`

Tool không bypass captcha, không lấy token từ trình duyệt, không scraping và không vượt giới hạn nền tảng. Người dùng chịu trách nhiệm sử dụng token hợp lệ và có quyền thao tác với comment/bài viết.

## Build/Publish Gợi Ý

Build Debug:

```powershell
dotnet build -c Debug
```

Publish self-contained Windows x64:

```powershell
dotnet publish -c Release -r win-x64 --self-contained true
```

Output publish nằm trong:

```text
bin\Release\net9.0-windows\win-x64\publish
```
