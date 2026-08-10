from __future__ import annotations

import requests


def push_plus(token: str, title: str, content: str) -> None:
    if not token:
        return
    try:
        requests.get(
            "http://www.pushplus.plus/send",
            params={"token": token, "title": title, "content": content},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"PushPlus 推送失败：{exc}")
