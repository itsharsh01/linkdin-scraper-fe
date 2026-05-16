"""
Streamlit dashboard for author bylines. Requires the FastAPI backend on API_BASE_URL (default :8000).
Run: streamlit run app.py
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

DEFAULT_API_BASE = "https://linkdin-scraper-be.onrender.com"


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def api_base() -> str:
    return (os.getenv("API_BASE_URL") or DEFAULT_API_BASE).rstrip("/")


def fetch_users() -> list[dict[str, Any]]:
    resp = requests.get(f"{api_base()}/users", timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_bylines(user_id: str, day: date) -> dict[str, Any]:
    resp = requests.get(
        f"{api_base()}/users/{user_id}/bylines",
        params={"date": day.isoformat()},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def user_label(user: dict[str, Any]) -> str:
    return f"{user.get('username', '?')} ({user.get('email', '')})"


@st.cache_data(ttl=60)
def cached_users() -> list[dict[str, Any]]:
    return fetch_users()


def _normalize_newlines(text: str) -> str:
    """Turn stored escape sequences into real line breaks for display."""
    if not text:
        return ""
    if "\\n" in text and text.count("\n") < text.count("\\n"):
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_subject_and_body(content: str) -> tuple[str, str]:
    text = _normalize_newlines(content).strip()
    if not text:
        return "", ""
    if text.lower().startswith("subject:"):
        first_line, _, remainder = text.partition("\n")
        subject = first_line.split(":", 1)[1].strip() if ":" in first_line else ""
        return subject, remainder.strip()
    return "", text


def format_copy_paste_email(llm: dict[str, Any]) -> tuple[str, str]:
    """
    Build metadata summary (markdown) and a plain-text email block ready to copy into a mail client.
    """
    score = llm.get("score")
    reason = (llm.get("reason") or "").strip()
    to_email = (llm.get("email") or "").strip()
    if to_email.lower() in {"not found", "n/a", "none", ""}:
        to_email = ""

    content = _normalize_newlines(str(llm.get("content") or ""))
    subject, body = _split_subject_and_body(content)

    # If subject was only in content block, use it; otherwise body may already include full letter
    lines: list[str] = []
    if to_email:
        lines.append(f"To: {to_email}")
        lines.append("")
    if subject:
        lines.append(f"Subject: {subject}")
        lines.append("")
    if body:
        lines.append(body)
    elif content and not subject:
        lines.append(content)

    email_block = "\n".join(lines).strip()
    email_block = re.sub(r"\n{3,}", "\n\n", email_block)

    score_display = "—" if score is None else str(score)
    meta = (
        f"**Match score:** {score_display}  \n"
        f"**Reason:** {reason or '—'}  \n"
        f"**Recipient:** {to_email or '—'}"
    )
    return meta, email_block


def render_llm_response(llm: dict[str, Any], item_id: str) -> None:
    meta, email_block = format_copy_paste_email(llm)
    st.markdown(meta)
    to_email = (llm.get("email") or "").strip()
    is_dm = to_email.lower() == "linkedin dm"
    if email_block:
        if is_dm:
            st.info("📩 Contact method is **LinkedIn DM** — copy the message below and send it as a LinkedIn message.")
        else:
            st.caption("Select all in the box below and copy (Ctrl+C) to paste into your email client.")
        st.text_area(
            "Email (copy-paste ready)" if not is_dm else "LinkedIn DM message (copy-paste ready)",
            value=email_block,
            height=min(420, 120 + email_block.count("\n") * 22),
            key=f"email_copy_{item_id}",
            label_visibility="visible",
        )
    else:
        st.warning("No email content in LLM response.")


def main() -> None:
    st.set_page_config(page_title="LinkedIn Byline Dashboard", layout="wide")
    st.title("Author bylines")
    st.caption(f"API: `{api_base()}`")

    try:
        users = cached_users()
    except requests.RequestException as exc:
        st.error(f"Could not load users. Is the backend running on {api_base()}?")
        st.code(str(exc))
        return

    if not users:
        st.warning("No users found. Create one via POST /users.")
        return

    col_user, col_date = st.columns(2)
    with col_user:
        user_options = {user_label(u): str(u["user_id"]) for u in users}
        selected_label = st.selectbox("User", options=list(user_options.keys()))
        selected_user_id = user_options[selected_label]
    with col_date:
        selected_date = st.date_input("Date", value=date.today())

    if st.button("Load bylines", type="primary"):
        st.session_state["load_bylines"] = True

    if not st.session_state.get("load_bylines"):
        st.info("Select user and date, then click **Load bylines**.")
        return

    try:
        payload = fetch_bylines(selected_user_id, selected_date)
    except requests.HTTPError as exc:
        st.error(f"API error: {exc}")
        if exc.response is not None:
            st.code(exc.response.text)
        return
    except requests.RequestException as exc:
        st.error(f"Request failed: {exc}")
        return

    items = payload.get("items") or []
    st.subheader(f"{payload.get('count', len(items))} bylines on {payload.get('date', selected_date)}")

    if not items:
        st.warning("No bylines for this user on the selected date.")
        return

    table_rows: list[dict[str, Any]] = []
    for item in items:
        created = item.get("created_at")
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                pass
        created_str = created.strftime("%Y-%m-%d %H:%M") if isinstance(created, datetime) else str(created or "")

        table_rows.append(
            {
                "author_name": item.get("author_name") or item.get("authorName") or "",
                "status": item.get("status"),
                "email_skip_reason": item.get("email_skip_reason") or "",
                "source_url": item.get("source_url") or "",
                "author_profile_url": item.get("author_profile_url")
                or item.get("authorProfileUrl")
                or "",
                "post_url": item.get("url") or "",
                "created_at": created_str,
                "text_preview": (item.get("text") or "")[:120],
            }
        )

    df = pd.DataFrame(table_rows)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "source_url": st.column_config.LinkColumn(
                "Source",
                display_text="Click here",
                help="Open source URL in a new tab",
            ),
            "author_profile_url": st.column_config.LinkColumn(
                "Author profile",
                display_text="Click here",
                help="Open author profile in a new tab",
            ),
            "post_url": st.column_config.LinkColumn(
                "Post",
                display_text="Click here",
                help="Open LinkedIn post in a new tab",
            ),
            "author_name": st.column_config.TextColumn("Author name", width="medium"),
            "status": st.column_config.CheckboxColumn("Status", disabled=True),
            "email_skip_reason": st.column_config.TextColumn("email_skip_reason", width="medium"),
            "text_preview": st.column_config.TextColumn("Post preview", width="large"),
            "created_at": st.column_config.TextColumn("Created", width="small"),
        },
    )

    st.divider()
    st.subheader("LLM responses (copy-paste email)")
    for idx, item in enumerate(items):
        name = item.get("author_name") or item.get("authorName") or f"Row {idx + 1}"
        llm = item.get("llm_response")
        item_id = str(item.get("id") or idx)
        with st.expander(f"{name} — {item_id[:8]}…"):
            if llm is None:
                st.write("_No LLM response yet._")
            elif not isinstance(llm, dict):
                st.write("_Invalid LLM response format._")
            else:
                render_llm_response(llm, item_id)


if __name__ == "__main__":
    main()
