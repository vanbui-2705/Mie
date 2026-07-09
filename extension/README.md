# FlowMeta Connector Extension

Chrome/Edge extension for running FlowMeta jobs in the user's real browser.

## Local install

1. Open Chrome or Edge.
2. Go to `chrome://extensions`.
3. Enable `Developer mode`.
4. Click `Load unpacked`.
5. Select this `extension` folder.
6. Open the extension popup.
7. Keep `Backend URL` as `http://localhost:8000`.
8. Choose a Facebook Account and click `Connect`.
9. Log in to Facebook normally in the same browser.

After the extension is connected, FlowMeta can send personal/group/share jobs to
the real browser instead of noVNC/Kasm.

## Notes

- Fanpage tasks still use Graph API from the backend.
- Personal profile, group, and external page jobs use the real browser.
- If Facebook shows checkpoint/2FA/captcha, the user handles it directly in
  their own browser.
