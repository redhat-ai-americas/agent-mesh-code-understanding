"""Submit Code Understanding pipeline and adhoc-query Jobs on OpenShift."""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

PIPELINE_JOB_PREFIX = "cu-pipeline-"
QUERY_JOB_PREFIX = "cu-query-"
PYTHON_IMAGE = "registry.access.redhat.com/ubi9/python-311"
WORKSPACE = "/opt/app-root/src"
REPO_LIST_FILE = "workflows/examples/code_understanding/assets/repos/repo_list.json"
JOB_SCRIPTS_CM = "code-understanding-job-scripts"
PIPELINE_SCRIPT = "/opt/job-scripts/run_pipelines.sh"
SERVICE_ACCOUNT = "pipeline-upload-job"
SECRET_NAME = "code-understanding-env"
GIT_SECRET_NAME = "git-credentials"
ADHOC_MARKER = "ADHOC RESULTS"


def current_namespace() -> str:
    env_ns = os.getenv("KFP_NAMESPACE", "").strip()
    if env_ns:
        return env_ns
    sa_ns = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
    if sa_ns.is_file():
        return sa_ns.read_text(encoding="utf-8").strip()
    return ""


def workflow_repo_url() -> str:
    url = os.getenv("AGENTMESH_REPO_URL", "").strip()
    if url:
        return url
    try:
        raw = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if raw.startswith("git@"):
            host, path = raw.split(":", 1)
            return f"https://{host[4:]}/{path}"
        return raw
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def workflow_repo_ref() -> str:
    job_ref = os.getenv("AGENTMESH_JOB_REPO_REF", "").strip()
    if job_ref:
        return job_ref
    ref = os.getenv("AGENTMESH_REPO_REF", "").strip()
    if ref:
        return ref
    try:
        return (
            subprocess.check_output(
                ["git", "branch", "--show-current"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            or "main"
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "main"


def analysis_image() -> str:
    registry = os.getenv("KFP_IMAGE_REGISTRY", "quay.io/ai-shadowman").strip()
    name = os.getenv("KFP_ANALYSIS_BASE_IMAGE_NAME", "data-indexing").strip()
    tag = os.getenv("KFP_ANALYSIS_BASE_IMAGE_TAG", "latest").strip()
    return f"{registry}/{name}:{tag}"


def k8s_clients() -> tuple[client.BatchV1Api, client.CoreV1Api, str]:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    ns = current_namespace()
    if not ns:
        raise RuntimeError("KFP_NAMESPACE is not set and no in-cluster namespace was found.")
    return client.BatchV1Api(), client.CoreV1Api(), ns


def cluster_status() -> dict[str, Any]:
    try:
        _, core, ns = k8s_clients()
        core.read_namespace(ns)
        return {
            "ok": True,
            "namespace": ns,
            "repo_url": workflow_repo_url(),
            "repo_ref": workflow_repo_ref(),
            "message": f"Connected to namespace {ns}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "namespace": current_namespace(),
            "repo_url": workflow_repo_url(),
            "repo_ref": workflow_repo_ref(),
            "message": str(exc),
        }


def git_setup(repo_url: str, repo_ref: str) -> str:
    return f"""
set -euo pipefail
if ! command -v git >/dev/null 2>&1; then
  echo "git is required but not installed in this image." >&2
  exit 1
fi
git config --global --add safe.directory {WORKSPACE}
git config --global credential.helper '!f() {{ echo "username=${{GIT_USERNAME}}"; echo "password=${{GIT_TOKEN}}"; }}; f'
rm -rf "{WORKSPACE}"/*
git -C {WORKSPACE} init -q
git -C {WORKSPACE} remote add origin "{repo_url}" 2>/dev/null || git -C {WORKSPACE} remote set-url origin "{repo_url}"
git -C {WORKSPACE} fetch --depth 1 origin "{repo_ref}" || git -C {WORKSPACE} fetch --depth 1 origin main
git -C {WORKSPACE} reset --hard FETCH_HEAD
test -f workflows/examples/code_understanding/scripts/run_adhoc_query.sh
""".strip()


def new_job_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{stamp}{uuid.uuid4().hex[:4]}"


def pod_template(
    *,
    name: str,
    image: str,
    command: str,
    extra_env: list[client.V1EnvVar],
    config_map_name: str | None = None,
    mount_job_scripts: bool = False,
    mount_git_credentials: bool = False,
) -> client.V1PodTemplateSpec:
    volume_mounts = [client.V1VolumeMount(name="workspace", mount_path=WORKSPACE)]
    volumes = [client.V1Volume(name="workspace", empty_dir=client.V1EmptyDirVolumeSource())]
    if mount_job_scripts:
        volume_mounts.append(
            client.V1VolumeMount(name="job-scripts", mount_path="/opt/job-scripts", read_only=True)
        )
        volumes.append(
            client.V1Volume(
                name="job-scripts",
                config_map=client.V1ConfigMapVolumeSource(name=JOB_SCRIPTS_CM, optional=False),
            )
        )
    if config_map_name:
        volume_mounts.append(
            client.V1VolumeMount(name="repo-list", mount_path="/repo-list", read_only=True)
        )
        volumes.append(
            client.V1Volume(
                name="repo-list",
                config_map=client.V1ConfigMapVolumeSource(name=config_map_name, optional=False),
            )
        )
    env_from = [
        client.V1EnvFromSource(
            secret_ref=client.V1SecretEnvSource(name=SECRET_NAME, optional=True)
        )
    ]
    if mount_git_credentials:
        env_from.append(
            client.V1EnvFromSource(
                secret_ref=client.V1SecretEnvSource(name=GIT_SECRET_NAME, optional=True)
            )
        )
    return client.V1PodTemplateSpec(
        spec=client.V1PodSpec(
            restart_policy="Never",
            service_account_name=SERVICE_ACCOUNT,
            containers=[
                client.V1Container(
                    name=name,
                    image=image,
                    command=["sh", "-c", command],
                    working_dir=WORKSPACE,
                    env=extra_env,
                    env_from=env_from,
                    volume_mounts=volume_mounts,
                )
            ],
            volumes=volumes,
        )
    )


def submit_pipeline_run(repos: list[dict[str, str]]) -> dict[str, str]:
    if not repos:
        raise ValueError("Select at least one repository.")

    batch, core, ns = k8s_clients()
    job_id = new_job_id()

    kfp_host = os.getenv(
        "KFP_HOST",
        f"https://ds-pipeline-dspa.{ns}.svc.cluster.local:8443",
    )
    target_path = os.getenv("KFP_DATA_GENERATION_OUTPUT_PATH", "target")
    graphrag_source_path = os.getenv("KFP_DATA_INDEXING_OUTPUT_PATH", "graph_rag_app/source")

    extra_env = [
        client.V1EnvVar(name="KFP_HOST", value=kfp_host),
        client.V1EnvVar(name="KFP_NAMESPACE", value=ns),
        client.V1EnvVar(name="KFP_DATA_GENERATION_OUTPUT_PATH", value=target_path),
        client.V1EnvVar(name="KFP_DATA_INDEXING_OUTPUT_PATH", value=graphrag_source_path),
    ]

    config_map_name = None
    if len(repos) == 1:
        mode_args = "--single-repo"
        extra_env.extend(
            [
                client.V1EnvVar(name="GIT_REPO", value=repos[0]["git_repo"]),
                client.V1EnvVar(name="GIT_BRANCH", value=repos[0]["git_branch"]),
            ]
        )
    else:
        mode_args = "--multi-repo"
        config_map_name = f"cu-repos-{job_id}"
        core.create_namespaced_config_map(
            ns,
            client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name=config_map_name, namespace=ns),
                data={"repo_list.json": json.dumps(repos, indent=2)},
            ),
        )

    apply_repo_list = ""
    if config_map_name:
        apply_repo_list = f"mkdir -p $(dirname {REPO_LIST_FILE}) && cp /repo-list/repo_list.json {REPO_LIST_FILE}\n"
    command = f"""
set -euo pipefail
pip install --quiet 'kfp>=2.0.0,<3.0.0' mlflow
test -f {PIPELINE_SCRIPT}
{apply_repo_list}sh {PIPELINE_SCRIPT} {mode_args}
""".strip()

    job_name = f"{PIPELINE_JOB_PREFIX}{job_id}"
    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=ns,
            labels={"app": "code-understanding-console", "role": "pipeline"},
        ),
        spec=client.V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=86400,
            template=pod_template(
                name="run-pipelines",
                image=PYTHON_IMAGE,
                command=command,
                extra_env=extra_env,
                config_map_name=config_map_name,
                mount_job_scripts=True,
            ),
        ),
    )
    batch.create_namespaced_job(ns, job)
    return {
        "job_name": job_name,
        "mode": "single-repo" if len(repos) == 1 else "multi-repo",
        "namespace": ns,
    }


def submit_adhoc_query(
    question: str,
    *,
    git_repo: str = "",
    git_branch: str = "main",
    use_global: bool | None = None,
    retry_count: int = 3,
) -> dict[str, str]:
    question = (question or "").strip()
    if not question:
        raise ValueError("Enter a question to query the index.")

    batch, core, ns = k8s_clients()
    job_id = new_job_id()
    repo_url = workflow_repo_url()
    repo_ref = workflow_repo_ref()
    if not repo_url:
        raise RuntimeError("AGENTMESH_REPO_URL is not set (needed to clone this workflow into the job).")

    if use_global is None:
        use_global = not bool(git_repo)

    cm_name = f"adhoc-query-{job_id}"
    core.create_namespaced_config_map(
        ns,
        client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=cm_name, namespace=ns),
            data={"question": question},
        ),
    )

    extra_env = [
        client.V1EnvVar(
            name="QUESTION",
            value_from=client.V1EnvVarSource(
                config_map_key_ref=client.V1ConfigMapKeySelector(name=cm_name, key="question")
            ),
        ),
        client.V1EnvVar(name="USE_GLOBAL", value="1" if use_global else "0"),
        client.V1EnvVar(name="RETRY_COUNT", value=str(retry_count)),
        client.V1EnvVar(name="GIT_REPO", value=git_repo),
        client.V1EnvVar(name="GIT_BRANCH", value=git_branch or "main"),
        client.V1EnvVar(name="GRAPHRAG_LOCAL_QUERY_SKIP_TLS_VERIFY", value="true"),
    ]

    command = f"""
set -euo pipefail
{git_setup(repo_url, repo_ref)}
cp /opt/job-scripts/mlflow_asset_loader.py workflows/examples/code_understanding/loaders/mlflow_asset_loader.py
cp /opt/job-scripts/default_asset_loader.py workflows/examples/code_understanding/loaders/default_asset_loader.py
workflows/examples/code_understanding/scripts/run_adhoc_query.sh
""".strip()

    job_name = f"{QUERY_JOB_PREFIX}{job_id}"
    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=ns,
            labels={"app": "code-understanding-console", "role": "query"},
        ),
        spec=client.V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=86400,
            template=pod_template(
                name="adhoc-query",
                image=analysis_image(),
                command=command,
                extra_env=extra_env,
                mount_job_scripts=True,
                mount_git_credentials=True,
            ),
        ),
    )
    batch.create_namespaced_job(ns, job)
    return {
        "job_name": job_name,
        "namespace": ns,
        "scope": "global" if use_global else f"{git_repo}@{git_branch}",
    }


def list_recent_jobs(limit: int = 15) -> list[dict[str, str]]:
    batch, _, ns = k8s_clients()
    jobs = batch.list_namespaced_job(ns, label_selector="app=code-understanding-console")
    items = sorted(
        jobs.items,
        key=lambda job: job.metadata.creation_timestamp or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:limit]
    rows = []
    for job in items:
        succeeded = job.status.succeeded or 0
        failed = job.status.failed or 0
        active = job.status.active or 0
        if succeeded:
            phase = "Succeeded"
        elif failed:
            phase = "Failed"
        elif active:
            phase = "Running"
        else:
            phase = "Pending"
        rows.append({"name": job.metadata.name, "status": phase})
    return rows


def job_pod_name(core: client.CoreV1Api, ns: str, job_name: str) -> str | None:
    pods = core.list_namespaced_pod(ns, label_selector=f"job-name={job_name}")
    if not pods.items:
        return None
    pods.items.sort(
        key=lambda pod: pod.metadata.creation_timestamp or datetime.min.replace(tzinfo=timezone.utc)
    )
    return pods.items[-1].metadata.name


def _as_text(logs: str | bytes | None) -> str:
    if logs is None:
        return ""
    if isinstance(logs, bytes):
        return logs.decode("utf-8", errors="replace")
    return str(logs)


def fetch_job_logs(core: client.CoreV1Api, ns: str, pod_name: str) -> str:
    """Read pod logs, preferring the tail where adhoc answers are written."""
    best = ""
    for tail_lines in (4000, 1500, None):
        try:
            kwargs = {"tail_lines": tail_lines} if tail_lines else {}
            text = _as_text(core.read_namespaced_pod_log(pod_name, ns, **kwargs))
            if not text:
                continue
            if ADHOC_MARKER in text or "Could not perform query:" in text:
                return text
            if len(text) > len(best):
                best = text
        except ApiException:
            continue
    return best


def wait_for_job(job_name: str, timeout_s: int = 1800, poll_s: float = 3.0) -> Iterator[dict[str, Any]]:
    batch, core, ns = k8s_clients()
    deadline = time.time() + timeout_s
    last_log = ""
    while time.time() < deadline:
        job = batch.read_namespaced_job(job_name, ns)
        succeeded = bool(job.status.succeeded)
        failed = bool(job.status.failed)
        logs = last_log
        pod = job_pod_name(core, ns, job_name)
        if pod:
            try:
                logs = _as_text(core.read_namespaced_pod_log(pod, ns, tail_lines=200))
            except ApiException:
                logs = last_log
        last_log = logs or last_log
        done = succeeded or failed
        if done:
            for _ in range(3):
                time.sleep(2)
                if pod:
                    logs = fetch_job_logs(core, ns, pod)
                    if logs:
                        last_log = logs
                        break
        yield {"done": done, "succeeded": succeeded, "logs": last_log}
        if done:
            return
        time.sleep(poll_s)
    yield {
        "done": True,
        "succeeded": False,
        "logs": last_log + "\nTimed out waiting for job.\n",
    }


def _decode_hex_escapes_as_utf8(text: str) -> str:
    """Decode literal \\xNN sequences (Python log repr) as UTF-8, not as code points."""
    import re

    pattern = re.compile(r"(?:\\x[0-9a-fA-F]{2})+")

    def repl(match: re.Match[str]) -> str:
        try:
            raw = bytes(int(byte_hex, 16) for byte_hex in re.findall(r"[0-9a-fA-F]{2}", match.group(0)))
            return raw.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return match.group(0)

    return pattern.sub(repl, text)


def _fix_residual_mojibake_artifacts(text: str) -> str:
    import re

    text = re.sub(r"\u00e2\s*\u0304", " ", text)
    text = re.sub(r"\u00e2(?=s\b)", "'", text)
    text = re.sub(r"\u00e2(?=\d)", "'", text)
    text = re.sub(r"\u00e2(?=[A-Za-z])", "-", text)
    return text.replace("\u00e2", "")


def fix_mojibake(text: str) -> str:
    """Repair UTF-8 text that was mis-decoded as Latin-1 or Windows-1252."""
    if any(0x80 <= ord(ch) <= 0xFF for ch in text) or "\u00e2" in text or "â" in text:
        for encoding in ("latin-1", "cp1252"):
            try:
                candidate = text.encode(encoding).decode("utf-8")
                if candidate != text:
                    text = candidate
                    break
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue

    for _ in range(2):
        if not any(marker in text for marker in ("â€", "Ã", "Â", "â€™", "â€œ", "ï»")):
            break
        try:
            text = text.encode("cp1252").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            break

    replacements = {
        "â€¯": " ",
        "â€‘": "-",
        "â€“": "-",
        "â€”": "-",
        "â€™": "'",
        "â€œ": '"',
        "â€\x9d": '"',
        "â€˜": "'",
        "Ã©": "e",
        "Ã§": "c",
        "Ã¨": "e",
        "Ã¢": "a",
        "Ã´": "o",
        "Ã¼": "u",
        "Â ": " ",
        "Â": "",
        "ï»¿": "",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return _fix_residual_mojibake_artifacts(text)


def _sanitize_unicode(text: str) -> str:
    import re
    import unicodedata

    text = fix_mojibake(text)
    text = unicodedata.normalize("NFKC", text)
    cleaned: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Mn":
            continue
        if cat.startswith("Z"):
            cleaned.append(" ")
        elif cat == "Cf" or (cat == "Cc" and ch not in "\n\t"):
            continue
        elif ord(ch) > 0xFFFF:
            continue
        else:
            cleaned.append(ch)
    text = "".join(cleaned)
    text = _normalize_unicode_punctuation(text)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text


def _normalize_unicode_punctuation(text: str) -> str:
    for ch in ("\u202f", "\u00a0", "\u2009", "\u200a"):
        text = text.replace(ch, " ")
    for ch in ("\u2011", "\u2010", "\u2013", "\u2014"):
        text = text.replace(ch, "-")
    for ch in ("\u2018", "\u2019"):
        text = text.replace(ch, "'")
    for ch in ("\u201c", "\u201d"):
        text = text.replace(ch, '"')
    return text


def _improve_markdown(text: str) -> str:
    import re

    # Remove invisible chars that break **bold** parsing.
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)
    text = re.sub(r"\*\*([^*\n]+?)\*\*", lambda m: f"**{m.group(1).strip()}**", text)
    text = re.sub(r"(?<!\n)(\*\*\d+\.)", r"\n\n\1", text)
    text = re.sub(r"  \n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def format_chat_answer(text: str) -> str:
    """Normalize adhoc query text for readable Streamlit markdown."""
    import ast
    import re

    text = (text or "").strip()
    if not text:
        return text

    if len(text) > 2 and text[0] == text[-1] and text[0] in "\"'":
        try:
            text = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            pass

    if "\\x" in text:
        text = _decode_hex_escapes_as_utf8(text)
    if "\\n" in text:
        text = text.replace("\\n", "\n").replace("\\t", "\t")

    text = _sanitize_unicode(text)

    text = re.sub(r"#+\s*ADHOC RESULTS\s*#+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^#+\s*$", "", text, flags=re.MULTILINE)

    text = _improve_markdown(text)
    text = _fence_tree_blocks(text)
    return text.strip()


def _fence_tree_blocks(text: str) -> str:
    """Wrap ASCII directory trees in fenced code blocks for markdown rendering."""
    import re

    lines = text.splitlines()
    out: list[str] = []
    block: list[str] = []

    def flush() -> None:
        nonlocal block
        if not block:
            return
        out.append("```text")
        out.extend(block)
        out.append("```")
        block = []

    tree_line = re.compile(r"[│├└─]")
    for line in lines:
        if tree_line.search(line):
            block.append(line)
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(out)


def format_job_logs(logs: str | bytes | None) -> str:
    """Clean Kubernetes job logs for display in the console."""
    import re

    text = _as_text(logs).strip()
    if not text:
        return ""

    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"\r[^\n]*", "", text)
    if "\\n" in text and text.count("\n") < text.count("\\n"):
        text = text.replace("\\n", "\n").replace("\\t", "\t")
    if "\\x" in text:
        text = _decode_hex_escapes_as_utf8(text)

    skip_markers = (
        "[notice]",
        "FutureWarning:",
        "warnings.warn(",
        "site-packages/kfp",
        "site-packages/urllib3",
        "InsecureRequestWarning",
    )
    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(marker in stripped for marker in skip_markers):
            continue
        cleaned.append(line.rstrip())

    return "\n".join(cleaned[-120:])


def extract_pipeline_summary(logs: str | bytes | None) -> dict[str, Any]:
    """Pull human-readable highlights from a pipeline submit job."""
    summary: dict[str, Any] = {"submitted": [], "run_url": "", "experiment_url": ""}
    for line in format_job_logs(logs).splitlines():
        if "OK:" in line and "submitted" in line:
            summary["submitted"].append(line.strip().removeprefix("OK:").strip())
        elif line.startswith("Triggering "):
            summary["submitted"].append(line.strip())
        elif "Run details:" in line:
            summary["run_url"] = line.split("Run details:", 1)[-1].strip()
        elif "Experiment details:" in line:
            summary["experiment_url"] = line.split("Experiment details:", 1)[-1].strip()
        elif line.strip() == "All done.":
            summary["done"] = True
    return summary


def extract_adhoc_answer(logs: str | bytes | None) -> str:
    logs = _as_text(logs)
    import re

    logs = re.sub(r"\x1b\[[0-9;]*m", "", logs)
    logs = re.sub(r"\r[^\n]*", "", logs)

    idx = logs.find(ADHOC_MARKER)
    if idx != -1:
        body = logs[idx + len(ADHOC_MARKER) :]
        lines = [
            line
            for line in body.splitlines()
            if ADHOC_MARKER not in line and set(line.strip()) not in ({"#"}, {"-"})
        ]
        answer = "\n".join(lines).strip()
        if answer:
            return format_chat_answer(answer)

    for line in reversed(logs.splitlines()):
        stripped = line.strip()
        if stripped.startswith("Could not perform query:"):
            return stripped
        if stripped.startswith("TypeError:") or stripped.startswith("ValueError:"):
            return f"Query failed: {stripped}"
        if stripped.startswith("Error:") and "notice" not in stripped.lower():
            return stripped

    return (
        "The query job finished but no answer was found in the logs. "
        "Try again in a moment, or check the job logs in the sidebar."
    )
