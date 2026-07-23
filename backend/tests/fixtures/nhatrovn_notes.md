# nhatrovn.vn portal — discovery notes (Task 1)

Portal: `https://quanly.nhatrovn.vn` (Laravel + jQuery + KendoUI, server-rendered HTML — no JSON API).
Company account with legal authorization to use the rental data. Captured 2026-07-23 from a
live logged-in session (`/main/room-sale/init`, HCMC, districts of Bình Chánh region).

All values below were captured structurally (no tokens/cookies/passwords were read or stored).

---

## 1. Room list endpoint

`POST https://quanly.nhatrovn.vn/main/room-sale/search` → **200, returns HTML fragment**
(a `<div class="row">` of room cards). Parse with BeautifulSoup. Infinite-scroll pagination
(no page number): send the `data-key` of the last card seen as `_lastKey` to get the next batch;
empty `_lastKey` returns the first batch.

### Form fields (`form#f-room-sale`, method POST) → search body params

Body is `application/x-www-form-urlencoded`. Captured payload:

| Param                     | Example value | Meaning |
|---------------------------|---------------|---------|
| `_lastKey`                | `` (empty)    | Pagination cursor = `data-key` of last card; empty = first page |
| `provincial-code`         | `79`          | Province GSO code (79 = TP.HCM, 92 = Cần Thơ, …) — **single** |
| `district-code`           | `W10=`        | **base64(JSON array)** of district codes. `W10=` = base64 `[]` (none). e.g. `["785"]` → base64 |
| `ward-code`               | `W10=`        | **base64(JSON array)** of ward codes, same encoding as district |
| `company-filter`          | `` | company scope filter (leave empty) |
| `house-id`                | `` | specific house filter (leave empty for all) |
| `price-room`              | `` | price bucket filter |
| `has-image`               | `ALL`         | image filter (`ALL` = no filter) |
| `house-address`           | `` | free-text address filter |
| `input-search`            | `` | free-text search |
| `allow-sale`              | `` | |
| `_data_filter_furniture`  | `` | |
| `ttro-coc`                | `` | |
| `room-status-filter`      | `` | status filter (empty = all) |
| `sort-gia-phong`          | `` | |
| `house-remark`            | `` | |
| `sort-by`                 | `1`           | sort order |

**Area selection → params:** `provincial-code` = one province code; `district-code` /
`ward-code` = base64 of a JSON array of the selected codes. To fetch one district: set
`provincial-code` and `district-code = base64(json.dumps(["<district_code>"]))`.
The option lists come from the selects on the page:

- `select#provincial-code` — 21 options, `value` = province code, text = province name.
- `select#district-code-multi` — options load after province chosen; `value` = district code
  (e.g. `785=Huyện Bình Chánh`, `783=Huyện Củ Chi`), text = district name.
- `select#ward-code-multi` — options load after district chosen.

> The adapter can fetch the province/district/ward option lists by GETting the room-sale page
> (or the KendoUI cascade endpoints) — but for the feature we only need the codes the user picked
> in our own UI, which we pass straight through as `provincial-code` + base64 district/ward arrays.

---

## 2. Auth / session (Laravel)

- Login page: `GET /login` (Laravel Blade form with hidden `@csrf` `_token` input).
- Logout: `/logout`.
- Cookies: `XSRF-TOKEN` (readable by JS, per Laravel) + a session cookie that is **httpOnly**
  (not visible to `document.cookie`). Requests send the CSRF value as header `X-XSRF-TOKEN`
  (url-decoded `XSRF-TOKEN` cookie). The `/search` POST carries **no** `_token` field, so CSRF
  travels in the header, not the body.

### Backend login flow (Task 4 `NhatrovnAdapter.login`)
1. `GET /login` with a cookie jar → receive `XSRF-TOKEN` + session cookie; scrape the hidden
   `_token` from the form.
2. `POST /login` with `_token`, username, password (fields TBD — inspect the login form; likely
   `email`/`username` + `password`).
3. Success = redirect (302) to the dashboard and an authenticated session cookie. Failure =
   200 with the login form re-rendered (validation errors).
4. Reuse the cookie jar for `/main/room-sale/search`; send `X-XSRF-TOKEN` header from the cookie.
5. On 401/redirect-to-login during search → session expired → re-login and retry once.

### ⚠️ OPEN QUESTION for the user (blocks credential-vs-cookie decision)
**Does nhatrovn login require an OTP / email code / captcha?**
- If **no** (plain username+password): store encrypted `username`+`password` in
  `RentalConfig.source_credentials_enc` (Fernet); backend logs in server-side as above.
  I (Claude) never type the password — the user enters it once in our own config form.
- If **yes** (OTP/captcha): server-side login is not possible. Fall back to **manual cookie mode**:
  the user logs in in their browser, we capture the session cookie (via the extension/network
  layer, since it is httpOnly) and store it encrypted; re-capture when it expires.

Default assumption for the plan: **plain username+password** (most nhatrovn accounts have no 2FA).
Adapter must detect an OTP/captcha step and raise a clear, actionable error if encountered.

---

## 3. Room card selectors (parser — Task 3 `parse_rooms`)

Container batch: each card is `div.content-room` (also `.col-md-6.col-lg-6.col-xlg-4.m-b-10`).
Recommended strategy: **label-driven** — find the `<span>` whose text starts with a known label,
take the next `<span>` sibling as the value. Robust against layout/column shifts.

| Field            | Selector / rule | Example |
|------------------|-----------------|---------|
| `external_room_id` | `div.content-room[data-key]` → attribute `data-key` (24-hex) | `a1a1…` |
| house id         | same node, attribute `data-house_key` | `b2b2…` |
| room code        | `p.text-color-room-caretaker span.span-house` → **1st** span | `B311` |
| address          | `span.span-house` texts after the `-` separator (skip code, skip `-`, skip `.d-none` phone) | `32/21 VÕ VĂN HÁT, X. Bình Chánh` |
| phone (hidden)   | `span.span-house.d-none` (masked in fixture — do not post publicly) | `0900000000` |
| listed date      | `span.small.fs-i.fs-9` (first) | `23/07/2026 10:15:46` |
| **price**        | label `Giá cho thuê:` → next `span.fw-700` (parent `div.small.text-red`) | `3,200,000` |
| **area**         | label `Diện tích:` → next `span.fw-800` | `20m2` |
| position (floor) | label `Vị trí:` → next `span.fw-800` | `Lầu 3` |
| deposit          | label `Cọc giữ chổ:` → next `span.fw-800` | `2,000,000` |
| **status**       | label `Trạng thái:` → next `span.fw-700` | `Trống` / `Đã thuê` |
| GoogleMap link   | `a.text-color-room-live.fs-10` → `href` | maps url |
| image            | `div.content-room img` → `src` = `/view-image-room/{house}/images-room/{house}/{room}/{img}.jpg` (needs auth to fetch) | |

Utility fees (optional, `div.col-6.col-lg-6.small > div > span + span.fw-700`):
Điện/Nước/Xe/Quản lý/Wifi/M.giặt/Thẻ/Phí DV. Amenities (Gác/Cửa sổ/Ban công, `✔`) in the
`.div-noi-that` block. Not required for the caption; capture into `RentalRoom.description` if useful.

**Status → posting:** only `Trạng thái: Trống` (vacant) rooms should be posted. `Đã thuê` (rented)
rooms are filtered out by the sync service.

Fixture: `nhatrovn_room_sale.html` (2 reconstructed cards, sanitized) supports every selector above.
It is a faithful reconstruction — the live HTML could not be exported verbatim because the browser
content filter blocks logged-in page dumps (they contain session tokens). Structure, classes, and
nesting were captured from the live DOM tree.

---

## 4. Images note
Room images sit behind auth (`/view-image-room/...` needs the session cookie). Posting images to
Facebook would require downloading them with the authenticated session first — **deferred**; the
first version posts the caption text only (`RentalRoom.images_json` stores the remote URLs).
