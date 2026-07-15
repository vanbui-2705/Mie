# FlowMeta Connector Extension

Chrome/Edge extension for running FlowMeta jobs in the user's real browser.

After every extension update, open `chrome://extensions`, make sure only one unpacked FlowMeta Connector is installed, then click **Reload**. The popup and background worker must use the same version (current: `0.1.29`).

## Local install

1. Open Chrome or Edge.
2. Go to `chrome://extensions`.
3. Enable `Developer mode`.
4. Click `Load unpacked`.
5. Select this `extension` folder.
6. Open the extension popup.
7. Sign in with the same FlowMeta account used on the web application.
8. Keep `Backend URL` as `http://localhost:8000`.
9. Choose a Facebook Account and click `Connect`.
10. Log in to Facebook normally in the same browser.

When updating an unpacked installation, click **Reload** on the extension card
in `chrome://extensions` before reopening the popup.

After the extension is connected, FlowMeta can send personal/group/share jobs to
the real browser instead of noVNC/Kasm.

## Notes

- Fanpage tasks still use Graph API from the backend.
- Personal profile, group, and external page jobs use the real browser.
- If Facebook shows checkpoint/2FA/captcha, the user handles it directly in
  their own browser.
- FlowMeta access tokens are stored in `chrome.storage.local`; logging out of
  the popup clears the token and selected Facebook account.
