# Module Catalog

Use this catalog to find the smallest relevant part of the project before
reading or changing code.

| Module | Owns | Architecture |
|---|---|---|
| Platform | Database, Redis, events, configuration, storage and subprocess foundations | [`platform`](modules/platform/ARCHITECTURE.md) |
| Identity and access | Login, OAuth, users, roles, permissions and tokens | [`identity-access`](modules/identity-access/ARCHITECTURE.md) |
| Facebook | Graph API, Facebook accounts and OAuth | [`facebook`](modules/facebook/ARCHITECTURE.md) |
| Automation | Comment, post, share, scheduling and task queues | [`automation`](modules/automation/ARCHITECTURE.md) |
| Browser execution | Browser sessions, Browserless and browser worker operations | [`browser`](modules/browser/ARCHITECTURE.md) |
| Proxy and profiles | Proxy leases, browser profiles and account environments | [`proxy-profiles`](modules/proxy-profiles/ARCHITECTURE.md) |
| Google Sheets | Sheet connections, campaigns, sync and writeback | [`sheets`](modules/sheets/ARCHITECTURE.md) |
| Rental | Room ingestion, media, matching and publication | [`rental`](modules/rental/ARCHITECTURE.md) |
| Flow Video | Reup, Gen, ASR, AI scoring, TTS and rendering | [`flow-video`](modules/flow-video/ARCHITECTURE.md) |
| Web console | Next.js routes, feature panels, auth state and API clients | [`web-console`](modules/web-console/ARCHITECTURE.md) |
| Desktop | Windows desktop client, licensing and local settings | [`desktop`](modules/desktop/ARCHITECTURE.md) |
| License Admin | Offline license-key generation and private-key storage | [`license-admin`](modules/license-admin/ARCHITECTURE.md) |
| Browser extension | Manifest V3 connector running in the user's browser | [`browser-extension`](modules/browser-extension/ARCHITECTURE.md) |
| Deployment | Compose, Docker, reverse proxies, TLS and persistent volumes | [`deployment`](modules/deployment/ARCHITECTURE.md) |
| Guide site | User-facing documentation website | [`guide-site`](modules/guide-site/ARCHITECTURE.md) |
| Legacy Facebook poster | Standalone Tkinter UCMAS posting application | [`legacy-facebook-poster`](modules/legacy-facebook-poster/ARCHITECTURE.md) |

## Task routing

| Task or symptom | Read first |
|---|---|
| 401, login, OAuth or permissions | Identity and access |
| Facebook token, page or Graph failure | Facebook |
| Comment/post/share job failure | Automation, then Browser execution |
| Browser login or session failure | Browser execution, then Proxy and profiles |
| Sheet sync or campaign issue | Google Sheets |
| Room scraping or rental posting | Rental |
| Reup, Gen, subtitle, image, audio or FFmpeg | Flow Video |
| UI state, request or rendering issue | Web console, then the owning backend module |
| License generation or admin private-key issue | License Admin |
| Container, port, certificate or volume issue | Deployment |
| Database, Redis, SSE or process lifecycle issue | Platform |

## Documentation rule

Module documents describe the current source of truth. When ownership,
entrypoints, contracts, storage or debug procedure changes, update the owning
module's `ARCHITECTURE.md` in the same commit.
