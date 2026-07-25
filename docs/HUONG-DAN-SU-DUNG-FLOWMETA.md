# Hướng dẫn sử dụng FlowMeta

> Tài liệu dành cho người dùng cuối của FlowMeta Automation Console.  
> Cập nhật theo giao diện ngày 23/07/2026.

## 1. FlowMeta dùng để làm gì?

FlowMeta hỗ trợ quản lý nhiều tài khoản Facebook và thực hiện các công việc:

- Quản lý Facebook Account, token và Fanpage.
- Kết nối trình duyệt Facebook để thao tác bằng phiên đăng nhập thật.
- Đăng bài lên Fanpage, trang cá nhân và Group.
- Tạo lịch đăng một lần hoặc lặp lại.
- Chỉnh sửa comment qua hàng đợi tác vụ.
- Chia sẻ bài viết sang Group hoặc Page bên ngoài.
- Quản lý proxy KiotProxy.
- Kết nối và kiểm tra nguồn Google Sheets.
- Quản lý người dùng và phân quyền.

Các menu hiển thị theo quyền của tài khoản. Nếu không thấy một chức năng, hãy liên hệ quản trị viên để được cấp quyền.

## 2. Bắt đầu nhanh

Thực hiện theo thứ tự sau trong lần sử dụng đầu tiên:

1. Mở đường dẫn FlowMeta do quản trị viên cung cấp.
2. Đăng ký tài khoản hoặc đăng nhập.
3. Mở **Accounts & Pages** và nhập Facebook Account theo định dạng `UID|TOKEN`.
4. Bấm **Check** để kiểm tra token.
5. Bấm **Sync page** để lấy danh sách Fanpage.
6. Nếu cần đăng lên trang cá nhân, Group hoặc dùng Auto Share, bấm **Connect Facebook**, đăng nhập Facebook trong cửa sổ được mở, sau đó bấm **Check browser**.
7. Chỉ bắt đầu Auto Post, Auto Share hoặc Lịch đăng khi mục tiêu hiển thị trạng thái khả dụng.

Luồng chuẩn:

```text
Nhập Account → Check token → Sync Page → Connect Facebook
       ↓
Chọn chức năng → Chọn mục tiêu → Nhập nội dung → Chạy tác vụ → Theo dõi kết quả
```

## 3. Đăng nhập và tài khoản FlowMeta

### 3.1. Đăng ký

Tại trang **Đăng ký**:

1. Nhập thông tin theo biểu mẫu.
2. Mật khẩu phải có ít nhất 8 ký tự.
3. Nhập lại mật khẩu chính xác.
4. Bấm **Đăng ký**.
5. Sau khi tạo thành công, hệ thống chuyển về trang đăng nhập.

### 3.2. Đăng nhập

Có thể đăng nhập bằng:

- Email hoặc tên đăng nhập và mật khẩu.
- Google, nếu quản trị viên đã bật.
- Facebook, nếu quản trị viên đã bật.

Sau khi đăng nhập thành công, hệ thống chuyển tới **Accounts & Pages**.

### 3.3. Quên mật khẩu

1. Tại trang đăng nhập, bấm **Quên mật khẩu?**
2. Nhập email đã đăng ký.
3. Bấm **Gửi liên kết**.
4. Mở liên kết đặt lại mật khẩu được gửi cho bạn.
5. Nhập mật khẩu mới có ít nhất 8 ký tự và bấm **Đổi mật khẩu**.

### 3.4. Đăng xuất

Bấm biểu tượng đăng xuất ở góc trên bên phải. Không nên dùng chung một phiên đăng nhập FlowMeta trên máy công cộng.

## 4. Accounts & Pages

Đây là nơi cần cấu hình trước khi chạy các chức năng Facebook.

### 4.1. Nhập Facebook Account

1. Bấm **Nhập UID|TOKEN**.
2. Dán danh sách, mỗi dòng một tài khoản.
3. Bấm nút xác nhận nhập.

Định dạng hỗ trợ:

```text
UID|TOKEN
UID|TOKEN|TÊN GỢI NHỚ
```

Ví dụ:

```text
1000123456789|EAAG...
1000987654321|EAAG...|Tài khoản bán hàng
```

Lưu ý:

- Không thêm dấu cách thừa quanh dấu `|`.
- Nếu UID đã tồn tại, hệ thống cập nhật token thay vì tạo bản ghi trùng.
- Hệ thống có thể tự lấy tên tài khoản từ Facebook.
- Token là dữ liệu nhạy cảm; không gửi token trong nhóm chat hoặc ảnh chụp màn hình.

### 4.2. Các nút thao tác

| Nút | Công dụng |
|---|---|
| **Check** | Kiểm tra token và cập nhật trạng thái tài khoản. |
| **Sync page** | Lấy hoặc cập nhật các Fanpage do tài khoản quản lý. |
| **Connect Facebook** | Mở trình duyệt từ xa để đăng nhập Facebook và lưu phiên. |
| **Check browser** | Kiểm tra phiên trình duyệt đã đăng nhập và sẵn sàng hay chưa. |
| **Làm mới** | Tải lại danh sách Account và Fanpage. |
| Biểu tượng xóa | Xóa Account hoặc mục tiêu tương ứng. |

### 4.3. Kết nối trình duyệt Facebook

Kết nối browser cần thiết khi:

- Đăng lên trang cá nhân.
- Đăng lên Group.
- Auto Share sang Group hoặc Page bên ngoài.
- Tác vụ yêu cầu thao tác trên giao diện Facebook.

Cách thực hiện:

1. Chọn đúng Account.
2. Bấm **Connect Facebook**.
3. Một cửa sổ trình duyệt từ xa sẽ mở. Nếu hệ thống hiển thị tài khoản Kasm, dùng thông tin đó để vào trình duyệt.
4. Đăng nhập Facebook và hoàn tất xác minh nếu Facebook yêu cầu.
5. Không đăng xuất Facebook sau khi hoàn tất.
6. Quay lại FlowMeta và bấm **Check browser**.
7. Chỉ chạy tác vụ khi trạng thái là **Browser ready** hoặc **Extension online**.

### 4.4. Ý nghĩa trạng thái thường gặp

| Trạng thái | Ý nghĩa / cách xử lý |
|---|---|
| **Live** | Token đang hoạt động. |
| **Chưa kiểm tra** | Bấm **Check**. |
| **Token out / Die** | Token không còn dùng được; nhập token mới. |
| **Checkpoint** | Facebook yêu cầu xác minh tài khoản. |
| **Long-lived / LL còn N ngày** | Token dài hạn; theo dõi số ngày còn lại. |
| **Chưa login / Cần connect** | Bấm **Connect Facebook** và đăng nhập. |
| **Browser ready** | Phiên browser đã sẵn sàng. |
| **Extension online** | Extension đang kết nối và có thể nhận tác vụ. |
| **Extension offline / Hết phiên** | Mở lại extension hoặc kết nối browser lại. |
| **Lỗi browser** | Bấm **Check browser**, đọc lỗi và đăng nhập lại nếu cần. |

### 4.5. Đồng bộ Fanpage

1. Chọn Account trong bảng bên trái.
2. Bấm **Sync page**.
3. Kiểm tra danh sách **Fanpage theo account** bên phải.
4. Xem Page ID và quyền của từng Page.

Nếu không thấy Page, hãy kiểm tra:

- Token còn Live.
- Facebook Account thực sự có quyền trên Page.
- Token có đủ quyền cần thiết.

## 5. Auto Post

Auto Post hỗ trợ đăng nội dung, liên kết, ảnh hoặc video lên các mục tiêu khả dụng.

### 5.1. Chuẩn bị mục tiêu

- Fanpage: nhập Account và bấm **Sync page**.
- Trang cá nhân: Account phải có **Browser ready** hoặc **Extension online**.
- Group: import Group tại **Auto Share** và bảo đảm browser của Account đã sẵn sàng.

Mục tiêu bị làm mờ hoặc không chọn được là mục tiêu chưa khả dụng. Di chuột vào mục tiêu để xem lý do nếu giao diện có hiển thị.

### 5.2. Tạo tác vụ đăng bài

1. Mở **Auto Post**.
2. Nhập **Message**.
3. Nếu cần, nhập **Link đính kèm**.
4. Bấm **Chọn file** để thêm ảnh hoặc video.
5. Đặt **Threads** từ 1 đến 20.
6. Chọn một hoặc nhiều nơi đăng ở cột **Nơi đăng mục tiêu**.
7. Bấm **Đăng lên N nơi**.
8. Theo dõi trạng thái Task: tổng số, thành công, chờ duyệt và thất bại.

Phải có ít nhất một trong ba loại dữ liệu: nội dung, link hoặc media.

### 5.3. Chọn Threads

- Threads càng cao thì càng nhiều mục tiêu được xử lý song song.
- Nên bắt đầu thấp, khoảng 1–3, để theo dõi độ ổn định.
- Tăng dần khi Account, browser và proxy hoạt động ổn định.
- Không nên đặt cao chỉ để chạy nhanh; Facebook có thể giới hạn hành vi bất thường.

### 5.4. Trạng thái kết quả

- **success**: đăng thành công.
- **pending review**: đã thao tác nhưng cần kiểm tra hoặc chờ Facebook xử lý.
- **failed**: thất bại; kiểm tra trạng thái Account, browser, quyền Page và nội dung lỗi.

## 6. Auto Comment

Màn hình này đưa tác vụ comment vào hàng đợi worker và hiển thị nhật ký xử lý.

### 6.1. Cấu hình tác vụ

1. Chọn hành động **Chỉnh sửa**, **Xóa** hoặc **Tạo comment mới**.
2. Chọn **Số luồng** từ 1 đến 200.
3. Với Chỉnh sửa/Xóa, nhập UID và link comment theo từng dòng; hai danh sách phải có cùng số dòng.
4. Với Tạo mới, nhập link bài viết, mỗi dòng một link.
5. Với Chỉnh sửa/Tạo mới, nhập nội dung hoặc chọn một ảnh.
6. Nếu có nhiều biến thể nội dung, ngăn cách bằng một dòng trống.
7. Cấu hình delay tối thiểu, tối đa và số vòng áp dụng delay.
8. Bấm **Bắt đầu**.

Ví dụ nội dung có ba biến thể:

```text
Nội dung thứ nhất

Nội dung thứ hai

Nội dung thứ ba
```

### 6.2. Theo dõi và dừng

Khi chạy, màn hình hiển thị:

- Tổng số tác vụ.
- Đã xử lý.
- Thành công.
- Thất bại.
- Đang chờ proxy.
- Nhật ký theo từng UID/link.

Bấm **Dừng** để gửi yêu cầu hủy tác vụ. Một công việc đang xử lý dở có thể cần một khoảng thời gian ngắn trước khi dừng hoàn toàn.

### 6.3. Ảnh comment

Bấm **Chọn ảnh** để tải JPEG, PNG, WebP hoặc GIF lên server. Mặc định file tối đa 10 MB; hệ thống kiểm tra cả MIME type và chữ ký nội dung. Trường đường dẫn vẫn cho phép nhập file đã có trên server, nhưng không nhập đường dẫn chỉ tồn tại trên máy cá nhân nếu worker chạy trong Docker/VPS.

## 7. Lịch đăng

Lịch đăng cho phép tạo một gói gồm một hoặc nhiều bài và chạy tự động theo thời gian.

### 7.1. Tạo lịch

1. Mở **Lịch đăng**.
2. Nhập **Tên lịch**.
3. Chọn **Bắt đầu lúc**.
4. Nhập nội dung cho **Bài 1**.
5. Thêm link, ảnh hoặc video nếu cần.
6. Bấm **Thêm bài** để tạo Bài 2, Bài 3...
7. Chọn chế độ lặp:
   - **Một lần**.
   - **Mỗi N phút**.
   - **Mỗi N giờ**.
   - **Mỗi N ngày**.
8. Nếu lặp, nhập **Giá trị** và có thể đặt **Dừng sau lúc**.
9. Chọn ít nhất một nơi đăng.
10. Bấm **Tạo lịch X bài cho Y nơi**.

Mỗi bài phải có ít nhất nội dung, liên kết hoặc media.

### 7.2. Thứ tự bài trong lịch

Nếu lịch có nhiều bài, hệ thống xử lý lần lượt theo danh sách. Khu vực **Danh sách lịch** hiển thị bài tiếp theo, thời gian chạy tiếp theo, lần chạy cuối và chu kỳ lặp.

### 7.3. Quản lý lịch

| Nút | Công dụng |
|---|---|
| **Chạy ngay** | Yêu cầu chạy lịch ngay, không cần chờ mốc tiếp theo. |
| **Tạm dừng** | Giữ lịch nhưng không chạy tự động. |
| **Tiếp tục** | Bật lại lịch đang tạm dừng. |
| **Xóa** | Xóa lịch khỏi hệ thống. |

Kiểm tra đúng múi giờ của máy và server trước khi tạo lịch quan trọng.

## 8. Auto Share

Auto Share dùng thao tác Share gốc của Facebook để chia sẻ một bài nguồn sang Group hoặc Page bên ngoài.

### 8.1. Chuẩn bị

1. Account dùng để share phải được nhập tại **Accounts & Pages**.
2. Account phải có phiên Facebook hoạt động trong browser/extension.
3. Import Group hoặc Page bên ngoài trước khi tạo campaign.

Auto Share không dùng danh sách Fanpage đã đồng bộ/quản lý làm target share.

### 8.2. Import Group

1. Chọn **Facebook Account dùng để share**.
2. Nhập mỗi Group trên một dòng.
3. Bấm **Import group**.

Định dạng:

```text
Tên Group|https://facebook.com/groups/...
https://facebook.com/groups/...
```

### 8.3. Import Page bên ngoài

Nhập Page public hoặc Page đang follow:

```text
Tên Page|https://facebook.com/ten-page
https://facebook.com/ten-page
```

Sau đó bấm **Import page ngoài**.

Nên dùng URL có ID hoặc slug chính xác. Hệ thống dùng ID/slug trong URL để chọn Page trong hộp Share, không tìm Page chỉ bằng tên.

### 8.4. Kiểm tra target

1. Tìm target trong danh sách.
2. Bấm biểu tượng **Check browser target**.
3. Chỉ chọn target có trạng thái khả dụng.

### 8.5. Tạo campaign

1. Nhập **Tên campaign**.
2. Chọn **Mode**:
   - **Share link**: chia sẻ link bài nguồn.
   - **Custom content + link**: thêm caption tùy chỉnh cùng link nguồn.
3. Dán **Link bài nguồn**.
4. Nhập **Caption tùy chỉnh** nếu cần.
5. Chọn các target.
6. Bấm **Share sang N target**.
7. Theo dõi success, pending review, failed và danh sách lỗi.

## 9. Proxy

FlowMeta hỗ trợ quản lý proxy thông qua KiotProxy.

### 9.1. Cấu hình

1. Nhập **Token Kiot**.
2. Nhập **API key proxy**, mỗi dòng một key.
3. Đặt **Lượt mỗi IP**.
4. Đặt **Kiểm tra mỗi (giây)**, tối thiểu 5 giây.
5. Kiểm tra **URL lấy IP mới** và **URL IP hiện tại**.
6. Bấm **Lưu cấu hình**.
7. Bấm **Bắt đầu**.

### 9.2. Nguyên tắc hoạt động

- Mỗi API key đại diện cho một nguồn proxy.
- **Lượt mỗi IP** là số tác vụ tối đa dùng IP trước khi yêu cầu đổi IP.
- Khi proxy đang đổi hoặc chưa sẵn sàng, tác vụ có thể hiển thị **chờ proxy**.
- Bấm **Dừng** trước khi chỉnh cấu hình.
- **Xóa tất cả** xóa toàn bộ proxy đã cấu hình và chỉ khả dụng khi hệ thống proxy đang dừng.

### 9.3. Khi proxy lỗi

Kiểm tra theo thứ tự:

1. Token Kiot còn hợp lệ.
2. API key được nhập đúng, mỗi dòng một key.
3. Tài khoản KiotProxy còn lượt hoặc còn hạn.
4. URL lấy IP mới và URL IP hiện tại đúng mẫu của nhà cung cấp.
5. Dừng rồi bắt đầu lại trình quản lý proxy.

## 10. Nguồn Google Sheets

Màn hình này dùng để kết nối, kiểm tra quyền và xem trước một worksheet.

Màn hình này quản lý kết nối. Sau khi lưu nguồn, dùng **Chiến dịch Sheets** để đồng bộ dòng và tạo publication job; việc lưu nguồn riêng lẻ không tự đăng bài.

### 10.1. Chuẩn bị trên Google Cloud

1. Tạo project trên Google Cloud.
2. Bật Google Sheets API và Google Drive API.
3. Tạo Service Account.
4. Tạo và tải khóa JSON của Service Account.
5. Mở Google Sheet cần dùng.
6. Chia sẻ Sheet cho email Service Account với quyền **Editor** nếu cần đọc và ghi.

### 10.2. Thêm nguồn

1. Nhập **Tên nguồn**, ví dụ `Nội dung phòng trọ`.
2. Nhập đúng **Tên worksheet**, ví dụ `Posts`.
3. Dán link Google Sheet hoặc Spreadsheet ID.
4. Chọn chu kỳ kiểm tra: 30 giây, 1 phút, 5 phút hoặc 15 phút.
5. Chọn múi giờ, thông thường là **Việt Nam (UTC+7)**.
6. Bấm **Chọn file** và chọn credentials JSON. File tối đa 1 MB.
7. Bấm **Kiểm tra kết nối**.
8. Xem kết quả: credentials hợp lệ, đọc được worksheet và quyền đọc/ghi.
9. Bấm **Lưu nguồn**.

### 10.3. Nếu kết nối chỉ đọc

1. Sao chép email Service Account từ kết quả kiểm tra.
2. Mở Google Sheet.
3. Bấm **Share/Chia sẻ**.
4. Thêm email Service Account với quyền **Editor**.
5. Quay lại FlowMeta và kiểm tra lại.

### 10.4. Quản lý nguồn đã lưu

- **Kiểm tra**: xác nhận kết nối vẫn hoạt động.
- **Mở Sheet**: mở file trên Google Sheets.
- **Xóa**: xóa kết nối khỏi FlowMeta; không xóa file Google Sheet gốc.

## 11. Chiến dịch Google Sheets

Mỗi campaign nối một worksheet với một hoặc nhiều target Facebook. Hệ thống tách rõ ba lớp: dòng nguồn, publication job theo target và kết quả ghi ngược.

### 11.1. Tạo campaign

1. Mở **Chiến dịch Sheets** và bấm tạo chiến dịch.
2. Chọn nguồn Google Sheets và các target Facebook.
3. Điền tên cột nội dung; thêm cột link/media nếu Sheet có dùng.
4. Chọn lịch:
   - **NOW**: tạo job ngay khi dòng hợp lệ được đồng bộ.
   - **EXACT**: lấy thời gian chính xác từ cột lịch trong Sheet.
   - **AUTO**: phân bổ vào các khung giờ và ngày trong tuần đã chọn.
5. Chọn timezone, giới hạn mỗi ngày, khoảng cách tối thiểu, retry và chính sách bài trễ.
6. Lưu rồi bấm **Đồng bộ ngay** để kiểm tra.

### 11.2. Theo dõi và xử lý

- Mỗi dòng hiển thị trạng thái nguồn và job riêng cho từng target.
- Trạng thái thành công chuẩn của publication job là **succeeded**.
- Có thể **Đăng ngay** một dòng chưa chạy hoặc **Hủy** job đang chờ.
- **Tạm dừng** ngăn campaign tạo/lấy job mới; **Tiếp tục** bật lại.
- URL bài đăng chỉ xuất hiện sau khi adapter trả kết quả chắc chắn.
- Không chạy lại job `pending_review` trước khi kiểm tra Facebook vì kết quả có thể đã được tạo nhưng chưa xác nhận được.

Thanh health ở đầu trang hiển thị job đang chờ, job lỗi, job treo quá lâu và lỗi của campaign/cấu hình trọ. Khi `stale_jobs` lớn hơn 0, kiểm tra log backend/browser-worker trước khi chạy thêm.

## 12. Đăng trọ tự động

Luồng này đọc phòng từ Nhatro.vn, tải media về kho dùng chung, tùy chọn mirror sang Google Sheets và tạo job Facebook theo group đã gán.

### 12.1. Cấu hình

1. Mở **Đăng trọ tự động** và tạo cấu hình.
2. Nhập tài khoản nguồn, tỉnh/thành, quận/huyện và số trang tối đa.
3. Chọn chu kỳ đồng bộ và độ trễ bài đầu tiên.
4. Nếu cần mirror, chọn kết nối Google Sheets và worksheet đích.
5. Lưu rồi bấm **Đồng bộ ngay**.

### 12.2. Quản lý phòng và job

- Kiểm tra trạng thái nguồn, lần nhìn thấy cuối, số ảnh nguồn/đã tải và lỗi mirror.
- Gán group cho từng phòng trước khi đăng.
- Mở lịch sử job để xem target, số lần thử, lỗi và URL bài.
- **Bỏ qua** hủy job chưa chạy; job đang chạy chuyển `pending_review` để tránh đăng trùng.
- **Thử lại** đặt các job `failed`, `canceled` hoặc `pending_review` về hàng chờ; không cho retry khi job vẫn đang dispatch/queued/running.
- Phòng `rented` hoặc `inactive` không nên tiếp tục gán group hay tạo bài mới.

## 13. Users

Chức năng này chỉ hiển thị khi tài khoản có quyền quản lý người dùng.

### 13.1. Tạo người dùng

1. Nhập **Username**.
2. Nhập mật khẩu tối thiểu 6 ký tự.
3. Chọn **Role**.
4. Bấm **Tạo người dùng**.

### 13.2. Cập nhật người dùng

Trong danh sách:

- Đổi Role nếu được phép.
- Chọn `active` để cho phép đăng nhập.
- Chọn `disabled` để vô hiệu hóa.
- Nhập mật khẩu mới nếu cần; để trống nếu không đổi.
- Bấm **Lưu**.

Không thể vô hiệu hóa hoặc xóa chính tài khoản đang đăng nhập.

## 14. Cài đặt

### 14.1. Delay mặc định

- **Delay từ (giây)**: thời gian chờ tối thiểu.
- **Delay đến (giây)**: thời gian chờ tối đa.
- **Sau mỗi N vòng**: số vòng hoàn thành trước khi áp dụng delay.

Nên đặt Delay đến lớn hơn hoặc bằng Delay từ.

### 14.2. Hành vi

- **Luồng song song tối đa**: từ 1 đến 50.
- **Post mỗi UID**: từ 1 đến 20.
- **Tự động kiểm tra token profile khi nhập**: kiểm tra token ngay sau khi import.

Bấm **Lưu cài đặt** để áp dụng hoặc **Đặt lại** để trở về giá trị mặc định trên biểu mẫu.

## 15. Cách xử lý lỗi thường gặp

### Không thấy menu chức năng

Tài khoản chưa có quyền tương ứng. Liên hệ quản trị viên.

### Trang không tải hoặc báo mất kết nối

1. Tải lại trang.
2. Kiểm tra Internet.
3. Đăng xuất rồi đăng nhập lại.
4. Nếu dùng link Quick Tunnel, hỏi quản trị viên link mới vì link tạm có thể thay đổi khi server khởi động lại.

### Token không Live

1. Bấm **Check**.
2. Nếu Token out/Die, nhập token mới.
3. Nếu Checkpoint, đăng nhập Facebook và hoàn tất xác minh.
4. Bấm **Sync page** lại sau khi token hoạt động.

### Không thấy Fanpage

- Kiểm tra token.
- Kiểm tra quyền của Account trên Fanpage.
- Bấm **Sync page**.
- Đăng nhập lại Facebook nếu quyền vừa thay đổi.

### Target không chọn được

- Đọc lý do hiển thị dưới target.
- Kết nối browser lại.
- Bấm **Check browser** hoặc **Check browser target**.
- Kiểm tra Account được gắn với đúng Group/Page.

### Tác vụ pending review

Mở Facebook bằng đúng Account và kiểm tra bài/comment thực tế. Không chạy lại hàng loạt ngay vì có thể tạo nội dung trùng.

### Tác vụ failed

Kiểm tra:

- Nội dung lỗi trong Task hoặc Nhật ký.
- Token và quyền Page.
- Trạng thái browser/extension.
- Proxy.
- Link nguồn hoặc target còn tồn tại.
- Facebook có yêu cầu checkpoint/xác minh hay không.

### Lịch chạy sai giờ

- Kiểm tra thời gian trên máy người dùng.
- Kiểm tra múi giờ server với quản trị viên.
- Với Google Sheets, chọn đúng **Việt Nam (UTC+7)** nếu dữ liệu dùng giờ Việt Nam.

## 16. Khuyến nghị sử dụng an toàn

- Chỉ dùng Account, token và nội dung mà bạn có quyền quản lý.
- Không chia sẻ token, credentials JSON hoặc mật khẩu Kasm.
- Chạy thử với một mục tiêu trước khi chọn hàng loạt.
- Bắt đầu với Threads thấp và delay hợp lý.
- Kiểm tra nội dung, link và media trước khi chạy.
- Không bấm chạy lại khi Task vẫn đang xử lý.
- Khi thấy checkpoint hoặc lỗi đăng nhập, dừng tác vụ và xử lý Account trước.
- Tuân thủ điều khoản, giới hạn và chính sách của Facebook, Google và nhà cung cấp proxy.

## 17. Checklist trước khi chạy chiến dịch

- [ ] Đã đăng nhập đúng tài khoản FlowMeta.
- [ ] Facebook Account đã được nhập đúng.
- [ ] Token hiển thị Live.
- [ ] Fanpage đã Sync hoặc browser hiển thị ready.
- [ ] Target đã được kiểm tra và có trạng thái khả dụng.
- [ ] Nội dung, link và media đã được kiểm tra.
- [ ] Threads và delay ở mức phù hợp.
- [ ] Proxy đã sẵn sàng nếu chiến dịch yêu cầu proxy.
- [ ] Đã thử với một target.
- [ ] Đã theo dõi Task/Nhật ký sau khi bấm chạy.
- [ ] Với Sheets: đã kiểm tra mapping cột, timezone và xem trước dòng nguồn.
- [ ] Với đăng trọ: media đã tải, mirror không lỗi và group đã gán đúng.
- [ ] Publication health không có stale job trước khi mở rộng chiến dịch.
- [ ] Đã kiểm tra bài thật trên Facebook và URL kết quả sau smoke test.
