"""Code Understanding console: catalog or custom repos, pipeline runs, and index chat."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from catalog import default_repo_entry, load_catalog, repo_key
from cluster import (
    cluster_status,
    extract_adhoc_answer,
    extract_pipeline_summary,
    format_chat_answer,
    format_job_logs,
    list_recent_jobs,
    submit_adhoc_query,
    submit_pipeline_run,
    wait_for_job,
)
from indexes import (
    default_query_key,
    list_indexed_repos,
    multi_repo_indexed,
    queryable_repos,
    repo_is_indexed,
)

CANNED_QUERIES = [
    (
        "What migration order would be recommended when refactoring to reduce breaking changes?",
        "Migration order for refactoring",
    ),
    (
        "Which modules or components would be riskiest to refactor first?",
        "Riskiest modules to refactor",
    ),
    (
        "What are the data stores in this codebase?",
        "Data stores in this codebase",
    ),
]

CHAT_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

  html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
  }

  #MainMenu, footer { visibility: hidden; }
  header[data-testid="stHeader"] {
    visibility: visible !important;
    background: transparent !important;
    height: 0 !important;
    min-height: 0 !important;
  }
  header [data-testid="stDecoration"] {
    display: none !important;
  }
  /* stExpandSidebarButton lives inside stToolbar — do not hide the whole toolbar. */
  header [data-testid="stToolbar"] {
    display: flex !important;
    position: fixed !important;
    top: 0.55rem !important;
    left: 0.55rem !important;
    z-index: 999999 !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 0 !important;
    min-height: 0 !important;
    height: auto !important;
    width: auto !important;
    gap: 0 !important;
  }
  header [data-testid="stToolbar"] button:not([data-testid="stExpandSidebarButton"]) {
    display: none !important;
  }
  button[data-testid="stExpandSidebarButton"] {
    display: none;
    align-items: center !important;
    justify-content: center !important;
    width: 2.1rem !important;
    height: 2.1rem !important;
    min-width: 2.1rem !important;
    min-height: 2.1rem !important;
    border: 1px solid #ddd !important;
    border-radius: 8px !important;
    background: #fff !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08) !important;
    color: #444 !important;
  }
  button[data-testid="stExpandSidebarButton"]:hover {
    border-color: #c9190b !important;
    color: #c9190b !important;
    background: #fff8f7 !important;
  }

  .stApp {
    background: #f7f7f5 !important;
  }
  .block-container {
    padding-top: 0.85rem;
    padding-bottom: 1.25rem;
    max-width: 960px;
  }
  h1 {
    font-weight: 600;
    letter-spacing: -0.03em;
    margin-bottom: 0;
    color: #1a1a1a !important;
    font-size: 1.65rem !important;
  }

  /* Sidebar */
  div[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #ebebeb !important;
  }
  div[data-testid="stSidebar"] h3 {
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.07em !important;
    color: #888 !important;
  }
  div[data-testid="stSidebar"] .stSuccess {
    background: #f0faf4 !important;
    border: 1px solid #c6e9d0 !important;
    color: #1e6b3a !important;
    border-radius: 8px !important;
    font-size: 0.82rem !important;
  }
  div[data-testid="stSidebar"] .stCaption {
    color: #666 !important;
    font-size: 0.8rem !important;
  }

  /* Tabs */
  .stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 1px solid #e8e8e8;
    background: transparent;
  }
  .stTabs [data-baseweb="tab"] {
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    color: #666 !important;
    padding: 0.6rem 1.1rem !important;
    border-bottom: 2px solid transparent !important;
    background: transparent !important;
  }
  .stTabs [aria-selected="true"] {
    color: #1a1a1a !important;
    border-bottom: 2px solid #c9190b !important;
    background: transparent !important;
  }

  /* Scope badge */
  .chat-scope {
    display: inline-flex;
    align-items: center;
    font-size: 0.78rem;
    font-weight: 500;
    padding: 0.22rem 0.7rem;
    border-radius: 999px;
    margin-top: 0.3rem;
  }
  .chat-scope-ready { background: #edf7f0; color: #1a6b38; border: 1px solid #c6e9d0; }
  .chat-scope-warn { background: #fef8ec; color: #9a6700; border: 1px solid #f0dfa0; }

  /* Chat controls — single slim row above the chat panel */
  div[data-testid="stVerticalBlock"]:has(#chat-controls-marker) {
    margin-bottom: 0.35rem !important;
  }
  div[data-testid="stVerticalBlock"]:has(#chat-controls-marker) [data-testid="stSelectbox"] {
    margin-bottom: 0 !important;
  }
  div[data-testid="stVerticalBlock"]:has(#chat-controls-marker) [data-testid="stSelectbox"] label {
    font-size: 0.75rem !important;
    font-weight: 500 !important;
    color: #777 !important;
    margin-bottom: 0.1rem !important;
    text-transform: none !important;
    letter-spacing: normal !important;
  }
  div[data-testid="stVerticalBlock"]:has(#chat-controls-marker) [data-testid="stSelectbox"] > div > div {
    min-height: 2rem !important;
    font-size: 0.84rem !important;
  }
  div[data-testid="stVerticalBlock"]:has(#chat-controls-marker) .stButton > button {
    margin-top: 1.15rem !important;
    height: 2rem !important;
    min-height: 2rem !important;
    padding: 0 0.65rem !important;
    font-size: 0.78rem !important;
  }

  /* Chat panel */
  div[data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid #e8e8e8 !important;
    background: #ffffff !important;
    border-radius: 16px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.03) !important;
  }
  div[data-testid="stVerticalBlockBorderWrapper"] > div {
    padding: 0.75rem 1.1rem 0.5rem !important;
  }

  .chat-welcome {
    text-align: center;
    padding: 2.75rem 1.5rem 1.25rem;
    color: #666;
    font-size: 0.9rem;
    line-height: 1.6;
  }
  .chat-welcome h4 {
    margin: 0 0 0.4rem;
    color: #1a1a1a;
    font-size: 1rem;
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  /* Suggestion chips */
  div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="column"] button {
    border-radius: 10px !important;
    font-size: 0.78rem !important;
    padding: 0.5rem 0.7rem !important;
    border: 1px solid #e0e0e0 !important;
    background: #f9f9f8 !important;
    color: #333 !important;
    height: auto !important;
    min-height: 2.4rem !important;
    white-space: normal !important;
    line-height: 1.4 !important;
    font-weight: 400 !important;
    transition: all 0.15s ease !important;
  }
  div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="column"] button:hover {
    border-color: #c9190b !important;
    color: #c9190b !important;
    background: #fff8f7 !important;
    box-shadow: 0 1px 4px rgba(201,25,11,0.08) !important;
  }

  /* Messages */
  div[data-testid="stChatMessage"] {
    background: transparent !important;
    padding: 0.45rem 0 !important;
    max-width: 85%;
  }
  div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-user"]) {
    margin-left: auto;
  }
  div[data-testid="stChatMessageContent"] {
    background: #f4f4f2 !important;
    border: 1px solid #ebebeb !important;
    border-radius: 16px 16px 4px 16px !important;
    padding: 0.7rem 1rem !important;
    line-height: 1.6 !important;
    font-size: 0.9rem !important;
    color: #1a1a1a !important;
    box-shadow: none !important;
  }
  div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-user"]) div[data-testid="stChatMessageContent"] {
    background: #fff5f4 !important;
    border-color: #f5d5d2 !important;
    border-radius: 16px 16px 16px 4px !important;
  }
  div[data-testid="stChatMessageContent"] pre {
    background: #f0f0ee !important;
    border: 1px solid #e0e0e0 !important;
    border-radius: 8px !important;
    padding: 0.75rem !important;
    font-size: 0.82rem !important;
    overflow-x: auto !important;
    white-space: pre-wrap !important;
  }
  div[data-testid="stChatMessageContent"] strong {
    color: #1a1a1a;
  }

  /* Input — unified bar so send button aligns with textarea */
  .stChatFloatingInputContainer {
    padding: 0 !important;
    bottom: 0 !important;
  }
  div[data-testid="stChatInput"] {
    padding: 0.6rem 0 0 !important;
  }
  div[data-testid="stChatInput"] > div {
    display: flex !important;
    flex-direction: row !important;
    align-items: flex-end !important;
    gap: 0.5rem !important;
    border: 1px solid #ddd !important;
    border-radius: 12px !important;
    background: #ffffff !important;
    padding: 0.35rem 0.4rem 0.35rem 0.85rem !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
  }
  div[data-testid="stChatInput"] > div:focus-within {
    border-color: #c9190b !important;
    box-shadow: 0 0 0 3px rgba(201,25,11,0.1) !important;
  }
  div[data-testid="stChatInput"] > div > div:first-child {
    flex: 1 1 auto !important;
    min-width: 0 !important;
  }
  div[data-testid="stChatInput"] textarea {
    border: none !important;
    border-radius: 0 !important;
    background: transparent !important;
    color: #1a1a1a !important;
    padding: 0.45rem 0 !important;
    margin: 0 !important;
    font-size: 0.9rem !important;
    line-height: 1.5 !important;
    min-height: 1.5rem !important;
    box-shadow: none !important;
    resize: none !important;
  }
  div[data-testid="stChatInput"] textarea::placeholder { color: #aaa !important; }
  div[data-testid="stChatInput"] textarea:focus {
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
  }
  div[data-testid="stChatInput"] button {
    flex: 0 0 2.25rem !important;
    width: 2.25rem !important;
    height: 2.25rem !important;
    min-width: 2.25rem !important;
    min-height: 2.25rem !important;
    align-self: flex-end !important;
    margin: 0 0 0.1rem 0 !important;
    padding: 0 !important;
    border-radius: 8px !important;
    background: #c9190b !important;
    border: none !important;
    transition: background 0.15s ease !important;
  }
  div[data-testid="stChatInput"] button:hover {
    background: #a81509 !important;
  }
  div[data-testid="stChatInput"] button svg {
    width: 1rem !important;
    height: 1rem !important;
  }

  div[data-testid="stSelectbox"] label {
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    color: #555 !important;
  }
  div[data-testid="stSelectbox"] > div > div {
    border-radius: 8px !important;
    border-color: #ddd !important;
    font-size: 0.88rem !important;
  }

  /* Spinner */
  div[data-testid="stSpinner"] { color: #888 !important; font-size: 0.88rem !important; }

  /* Buttons */
  .stButton > button[kind="secondary"] {
    border-radius: 8px !important;
    border: 1px solid #ddd !important;
    background: #fff !important;
    color: #444 !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
  }
  .stButton > button[kind="secondary"]:hover {
    border-color: #bbb !important;
    color: #1a1a1a !important;
  }

  /* Pipeline tab */
  .pipeline-repo-list {
    margin: 0.25rem 0 1rem;
    padding: 0.65rem 0.85rem;
    background: #fff;
    border: 1px solid #ebebeb;
    border-radius: 10px;
    font-size: 0.88rem;
    color: #333;
    line-height: 1.5;
  }
  .pipeline-repo-list strong {
    color: #1a1a1a;
    font-weight: 600;
  }
</style>
"""

SIDEBAR_EXPAND_JS = """
<script>
(function () {
  const doc = window.parent.document;
  if (!doc) return;

  function sidebarCollapsed() {
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    return !sidebar || sidebar.getBoundingClientRect().width < 20;
  }

  function openSidebar() {
    const expand = doc.querySelector('[data-testid="stExpandSidebarButton"]');
    if (expand) {
      expand.click();
      if (!sidebarCollapsed()) return;
    }
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    if (!sidebar) return;
    sidebar.style.setProperty("transform", "none", "important");
    sidebar.style.setProperty("width", "300px", "important");
    sidebar.style.setProperty("min-width", "300px", "important");
  }

  function syncExpandButton() {
    const expand = doc.querySelector('[data-testid="stExpandSidebarButton"]');
    if (!expand) return;
    expand.style.display = sidebarCollapsed() ? "flex" : "none";
    if (!expand.dataset.cuBound) {
      expand.dataset.cuBound = "1";
      expand.addEventListener("click", function () {
        setTimeout(function () {
          if (sidebarCollapsed()) openSidebar();
        }, 150);
      });
    }
  }

  syncExpandButton();
  setInterval(syncExpandButton, 500);
  window.parent.addEventListener("resize", syncExpandButton);
})();
</script>
"""

st.set_page_config(page_title="Code Understanding", layout="wide", initial_sidebar_state="expanded")
st.markdown(CHAT_CSS, unsafe_allow_html=True)
components.html(SIDEBAR_EXPAND_JS, height=0)


@st.cache_data(ttl=60)
def cached_indexes():
    return list_indexed_repos()


def init_state() -> None:
    if "custom_repos" not in st.session_state:
        st.session_state.custom_repos = []
    if "selected_keys" not in st.session_state:
        default = default_repo_entry()
        default_key = repo_key(default) if default else None
        st.session_state.selected_keys = {default_key} if default_key else set()
        if default and not any(repo_key(item) == default_key for item in load_catalog()):
            st.session_state.custom_repos.append(default)
    if "chat_repo_key" not in st.session_state:
        st.session_state.chat_repo_key = None
    if "chat" not in st.session_state:
        st.session_state.chat = []
    if "pipeline_job" not in st.session_state:
        st.session_state.pipeline_job = None
    if "pipeline_logs" not in st.session_state:
        st.session_state.pipeline_logs = ""
    if "pipeline_succeeded" not in st.session_state:
        st.session_state.pipeline_succeeded = None
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None
    if "active_query" not in st.session_state:
        st.session_state.active_query = None


def selected_repos() -> list[dict[str, str]]:
    catalog = load_catalog(st.session_state.custom_repos)
    return [item for item in catalog if repo_key(item) in st.session_state.selected_keys]


def render_indexed_sidebar(index_data: dict) -> None:
    st.sidebar.markdown("### Indexed repositories")
    if not index_data["ok"]:
        st.sidebar.caption(index_data.get("message") or "Could not load indexes.")
        return
    if index_data.get("message") and not index_data.get("indexes"):
        st.sidebar.caption(index_data["message"])
    indexes = index_data.get("indexes") or []
    if not indexes:
        st.sidebar.caption("No GraphRAG indexes found yet. Run a pipeline first.")
        return
    if multi_repo_indexed(indexes):
        st.sidebar.success("Combined multi-repo index")
    for item in indexes:
        if item.get("multi_repo"):
            label = "multi-repo (combined)"
        else:
            label = item.get("git_slug") or "unknown"
        when = item.get("indexed_at", "")
        st.sidebar.write(f"· `{label}`" + (f" — {when[:10]}" if when else ""))


def render_sidebar() -> dict:
    status = cluster_status()
    index_data = cached_indexes()
    st.sidebar.markdown("### Cluster")
    if status["ok"]:
        st.sidebar.success(status["message"])
    else:
        st.sidebar.error("Not connected")
        st.sidebar.caption(status["message"])
    st.sidebar.caption(f"Namespace · `{status.get('namespace') or 'unset'}`")
    st.sidebar.markdown("---")
    render_indexed_sidebar(index_data)
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Recent jobs")
    if status["ok"]:
        try:
            jobs = list_recent_jobs()
        except Exception as exc:
            st.sidebar.caption(str(exc))
            jobs = []
        for job in jobs[:6]:
            icon = "✓" if job["status"] == "Succeeded" else "✗" if job["status"] == "Failed" else "…"
            st.sidebar.caption(f"{icon} `{job['name']}`")
        if not jobs:
            st.sidebar.caption("No jobs yet.")
    return status


def render_repos(index_data: dict) -> None:
    st.subheader("Repositories")
    st.caption("Select catalog repos or add a custom git URL. One repo → single-repo; multiple → multi-repo.")
    indexes = index_data.get("indexes") or []
    catalog = load_catalog(st.session_state.custom_repos)
    default_count = len(load_catalog())

    col_a, col_b, col_c = st.columns([1, 1, 2])
    if col_a.button("Select all"):
        st.session_state.selected_keys = {repo_key(item) for item in load_catalog()}
        st.rerun()
    if col_b.button("Clear"):
        st.session_state.selected_keys = set()
        st.rerun()
    if col_c.button("Refresh indexes"):
        cached_indexes.clear()
        st.rerun()

    selected_now: set[str] = set()
    for index, item in enumerate(catalog):
        key = repo_key(item)
        widget_key = f"cb_{key}"
        if widget_key not in st.session_state:
            st.session_state[widget_key] = key in st.session_state.selected_keys
        label = f"{item['git_repo']} ({item['git_branch']})"
        if index >= default_count:
            label = f"[custom] {label}"
        if repo_is_indexed(item["git_repo"], item["git_branch"], indexes):
            label += " · indexed"
        if st.checkbox(label, key=widget_key):
            selected_now.add(key)
    st.session_state.selected_keys = selected_now

    with st.form("add_repo"):
        url = st.text_input("Git URL", placeholder="https://github.com/org/repo")
        branch = st.text_input("Branch", value="main")
        if st.form_submit_button("Add to selection"):
            url, branch = url.strip(), (branch or "main").strip()
            if url:
                entry = {"git_repo": url, "git_branch": branch}
                if not any(repo_key(e) == repo_key(entry) for e in st.session_state.custom_repos):
                    st.session_state.custom_repos.append(entry)
                st.session_state.selected_keys.add(repo_key(entry))
                st.rerun()

    selected = selected_repos()
    mode = "multi-repo" if len(selected) > 1 else "single-repo" if selected else "none"
    st.info(f"{len(selected)} selected · {mode}")


def render_pipelines(connected: bool) -> None:
    st.subheader("Run pipelines")
    selected = selected_repos()
    if not selected:
        st.warning("Select one or more repositories on the Repositories tab first.")
        return

    repo_lines = [
        f"<strong>{item['git_repo'].rsplit('/', 1)[-1]}</strong> "
        f"<span style='color:#888'>@ {item['git_branch']}</span>"
        for item in selected
    ]
    st.markdown(
        f'<div class="pipeline-repo-list">{" · ".join(repo_lines)}</div>',
        unsafe_allow_html=True,
    )

    btn_col, _ = st.columns([2.2, 2.8])
    with btn_col:
        if st.button(
            "Run Code Understanding",
            type="primary",
            disabled=not connected,
            use_container_width=True,
            key="run_pipeline_btn",
        ):
            try:
                result = submit_pipeline_run(selected)
                st.session_state.pipeline_job = result
                st.session_state.pipeline_logs = ""
                st.session_state.pipeline_succeeded = None
                cached_indexes.clear()
                with st.spinner("Waiting for pipeline submit job…"):
                    for update in wait_for_job(result["job_name"]):
                        st.session_state.pipeline_logs = update["logs"]
                        if update["done"]:
                            st.session_state.pipeline_succeeded = update["succeeded"]
                            break
            except Exception as exc:
                st.error(str(exc))

    job = st.session_state.pipeline_job
    if not job:
        st.caption("Indexing runs as a Kubeflow pipeline in the background after submit succeeds.")
        return

    job_name = job["job_name"]
    succeeded = st.session_state.pipeline_succeeded
    summary = extract_pipeline_summary(st.session_state.pipeline_logs)

    if succeeded is True:
        st.success(
            "Pipeline submitted to Kubeflow. Indexing runs in the background — "
            "use **Refresh indexes** on the Repositories tab in a few minutes."
        )
        for line in summary.get("submitted") or []:
            st.markdown(f"- {line}")
    elif succeeded is False:
        st.error("Pipeline submit job failed. Expand **Job output** below for details.")
    else:
        st.info(f"Job `{job_name}` is still running…")

    st.caption(f"Job ID: `{job_name}`")

    logs = format_job_logs(st.session_state.pipeline_logs)
    if logs:
        with st.expander("Job output", expanded=succeeded is False):
            st.code(logs, language="text")


def query_scope(selected: list[dict[str, str]]) -> tuple[str, str, bool]:
    if len(selected) == 1:
        return selected[0]["git_repo"], selected[0]["git_branch"], False
    return "", "main", True


def scope_badge(selected: list[dict[str, str]], indexes: list[dict]) -> tuple[str, str]:
    git_repo, git_branch, use_global = query_scope(selected)
    if use_global:
        if multi_repo_indexed(indexes):
            return "chat-scope-ready", "Combined index ready"
        return "chat-scope-warn", "Run multi-repo pipeline first"
    short = git_repo.rsplit("/", 1)[-1]
    if repo_is_indexed(git_repo, git_branch, indexes):
        return "chat-scope-ready", f"{short} · indexed"
    return "chat-scope-warn", f"{short} · not indexed yet"


def run_query(question: str, git_repo: str, git_branch: str, use_global: bool) -> str:
    result = submit_adhoc_query(
        question,
        git_repo=git_repo,
        git_branch=git_branch,
        use_global=use_global,
    )
    answer = ""
    for update in wait_for_job(result["job_name"]):
        if update["done"]:
            answer = extract_adhoc_answer(update["logs"])
            if not update["succeeded"] and "Could not perform query" not in answer:
                answer = "The query job failed. Try again after indexing completes."
            break
    return answer or "No answer was returned."


def render_suggestions() -> None:
    st.markdown(
        '<div class="chat-welcome">'
        "<h4>What would you like to know?</h4>"
        "Pick a starter question or type your own below."
        "</div>",
        unsafe_allow_html=True,
    )
    chip_cols = st.columns(len(CANNED_QUERIES))
    for col, (full_q, label) in zip(chip_cols, CANNED_QUERIES):
        with col:
            if st.button(label, key=f"suggest_{hash(full_q)}", use_container_width=True):
                st.session_state.pending_question = full_q
                st.rerun()


def render_assistant_message(content: str) -> None:
    st.markdown(format_chat_answer(content))


def render_chat_repo_select(indexes: list[dict]) -> dict | None:
    catalog = load_catalog(st.session_state.custom_repos)
    options = queryable_repos(indexes, catalog)
    if not options:
        return None

    if st.session_state.chat_repo_key not in {o["key"] for o in options}:
        st.session_state.chat_repo_key = default_query_key(options)

    labels = [o["label"] for o in options]
    current = st.session_state.chat_repo_key or default_query_key(options)
    current_idx = next((i for i, o in enumerate(options) if o["key"] == current), 0)

    chosen_label = st.selectbox(
        "Repository",
        labels,
        index=current_idx,
        key="chat_repo_select",
        help="Only repositories with a completed GraphRAG index are listed.",
    )
    option = next(o for o in options if o["label"] == chosen_label)
    st.session_state.chat_repo_key = option["key"]

    if not option.get("use_global"):
        st.session_state.selected_keys = {option["key"]}

    return option


def render_query(connected: bool, index_data: dict) -> None:
    indexes = index_data.get("indexes") or []
    options = queryable_repos(indexes, load_catalog(st.session_state.custom_repos))

    if not options:
        st.warning("No indexed repositories yet. Run a pipeline on the Repositories tab first.")
        return

    st.markdown('<span id="chat-controls-marker"></span>', unsafe_allow_html=True)
    spacer_col, repo_col, clear_col = st.columns([3.2, 4.8, 0.7], vertical_alignment="bottom")
    with spacer_col:
        pass
    with repo_col:
        query_target = render_chat_repo_select(indexes)
    with clear_col:
        if st.button("Clear", use_container_width=True, key="clear_chat"):
            st.session_state.chat = []
            st.session_state.active_query = None
            st.rerun()

    if not query_target:
        return

    git_repo = query_target["git_repo"]
    git_branch = query_target["git_branch"]
    use_global = bool(query_target.get("use_global"))

    chat_box = st.container(height=720, border=True)
    with chat_box:
        empty = not st.session_state.chat and not st.session_state.active_query
        if empty:
            render_suggestions()
        for message in st.session_state.chat:
            with st.chat_message(message["role"]):
                if message["role"] == "assistant":
                    render_assistant_message(message["content"])
                else:
                    st.markdown(message["content"])
        if st.session_state.active_query:
            with st.chat_message("assistant"):
                with st.spinner("Searching the index…"):
                    aq = st.session_state.active_query
                    try:
                        answer = run_query(
                            aq["question"],
                            aq["git_repo"],
                            aq["git_branch"],
                            aq["use_global"],
                        )
                    except Exception as exc:
                        answer = f"**Something went wrong.** {exc}"
                    st.session_state.chat.append({"role": "assistant", "content": answer})
                    st.session_state.active_query = None
                    render_assistant_message(answer)
                    st.rerun()

    question = st.session_state.pending_question
    prompt = st.chat_input("Ask about the indexed code…", key="chat_prompt")
    if prompt:
        question = prompt
    if not question or st.session_state.active_query:
        return
    st.session_state.pending_question = None

    if not connected:
        st.error("Connect to the OpenShift project before querying.")
        return

    st.session_state.chat.append({"role": "user", "content": question})
    st.session_state.active_query = {
        "question": question,
        "git_repo": git_repo,
        "git_branch": git_branch,
        "use_global": use_global,
    }
    st.rerun()


def main() -> None:
    init_state()
    st.title("Code Understanding")
    status = render_sidebar()
    index_data = cached_indexes()
    repos_tab, pipelines_tab, query_tab = st.tabs(["Repositories", "Run pipelines", "Chat"])
    with repos_tab:
        render_repos(index_data)
    with pipelines_tab:
        render_pipelines(status["ok"])
    with query_tab:
        render_query(status["ok"], index_data)


if __name__ == "__main__":
    main()
