from __future__ import annotations
import re, unicodedata

def normalize_vn(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text or ""))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"\s+", " ", text).strip()

def match_group_ids(district_name: str, groups) -> list[str]:
    key = normalize_vn(district_name)
    for prefix in ("quan ", "huyen ", "thi xa ", "tp "):
        if key.startswith(prefix):
            key = key[len(prefix):]
    key = key.strip()
    if not key:
        return []
    out: list[str] = []
    for g in groups:
        name = normalize_vn(getattr(g, "group_name", "") or "")
        if key and key in name:
            out.append(str(getattr(g, "group_id", "") or ""))
    return [gid for gid in out if gid]
