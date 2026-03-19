#!/usr/bin/env python3
"""
Unified setup entry point for the self-hosted-memory-assistants meta-repo.

This script prepares configuration for:
  - mycelia
  - chronicle
  - ushadow

It keeps the orchestration at the meta-repo level so the subrepositories can
continue to evolve independently.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / ".setup.env"
CONFIG_TEMPLATE = ROOT / ".setup.env.example"
ENV_KEY_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


@dataclass
class ProjectStatus:
    name: str
    state: str
    existing_files: list[str]
    missing_files: list[str]
    missing_values: list[str]
    notes: list[str]


def log(message: str) -> None:
    print(message)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def relpath(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = raw_line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        values[key] = value
    return values


def is_truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def is_sensitive_placeholder(value: str | None) -> bool:
    if value is None:
        return True

    normalized = value.strip().lower()
    if not normalized:
        return True

    placeholder_prefixes = (
        "your-",
        "your_",
        "change-me",
        "change_me",
        "sk-xxxxx",
        "hf_xxxxx",
        "mycelia_1111",
        "111111111111",
    )
    placeholder_values = {
        "your-openai-key-here",
        "your-deepgram-key-here",
        "your-huggingface-token-here",
        "your-super-secret-jwt-key-here-make-it-random-and-long",
    }
    return normalized in placeholder_values or normalized.startswith(placeholder_prefixes)


def has_required_value(
    mapping: dict[str, str],
    key: str,
    *,
    reject_placeholders: bool = False,
) -> bool:
    value = mapping.get(key)
    if is_blank(value):
        return False
    if reject_placeholders and is_sensitive_placeholder(value):
        return False
    return True


def masked(value: str | None) -> str:
    if is_blank(value):
        return "empty"

    value = value or ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def prompt_text(
    label: str,
    current: str,
    *,
    interactive: bool,
    secret: bool = False,
    allow_blank: bool = True,
    default: str = "",
    note: str = "",
) -> str:
    if not interactive:
        return current if not is_blank(current) else default

    suffix = f" ({note})" if note else ""
    while True:
        if secret:
            current_hint = ""
            if not is_blank(current):
                current_hint = f" [{masked(current)}]"
            entered = getpass.getpass(f"{label}{suffix}{current_hint}: ").strip()
        else:
            default_value = current if not is_blank(current) else default
            default_hint = f" [{default_value}]" if default_value else ""
            entered = input(f"{label}{suffix}{default_hint}: ").strip()

        if not entered:
            entered = current if not is_blank(current) else default

        if entered or allow_blank:
            return entered

        log("Value is required.")


def choose_existing_mode(
    project_name: str,
    existing_files: list[str],
    *,
    interactive: bool,
    overwrite_existing: bool,
    keep_existing: bool,
) -> str:
    if overwrite_existing:
        return "override"
    if keep_existing or not interactive or not existing_files:
        return "keep"

    log("")
    log(f"{project_name}: existing setup detected")
    for path in existing_files:
        log(f"  - {path}")

    answer = input(
        "Keep existing values and only fill missing ones? [Y/n]: "
    ).strip().lower()
    return "override" if answer in {"n", "no"} else "keep"


def merge_env_updates(
    existing_env: dict[str, str],
    desired_updates: dict[str, str],
    *,
    mode: str,
) -> dict[str, str]:
    merged: dict[str, str] = {}
    for key, desired in desired_updates.items():
        existing = existing_env.get(key)
        if mode == "keep" and not is_blank(existing) and not is_sensitive_placeholder(existing):
            merged[key] = existing
        else:
            merged[key] = desired
    return merged


def upsert_env_file(
    target: Path,
    updates: dict[str, str],
    *,
    template: Path | None = None,
    dry_run: bool = False,
    replace_existing: bool = False,
) -> None:
    created_from_template = False

    if replace_existing:
        if template is not None and template.exists():
            lines = template.read_text().splitlines()
            created_from_template = True
        else:
            lines = []
    elif target.exists():
        lines = target.read_text().splitlines()
    elif template is not None and template.exists():
        lines = template.read_text().splitlines()
        created_from_template = True
    else:
        lines = []

    if created_from_template:
        action = "reset" if replace_existing and target.exists() else "create"
        if template is not None:
            log(f"{action} {relpath(target)} from {relpath(template)}")
        else:
            log(f"{action} {relpath(target)}")

    key_positions: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = ENV_KEY_RE.match(line)
        if match:
            key_positions[match.group(1)] = index

    for key, value in updates.items():
        rendered = f"{key}={value}"
        if key in key_positions:
            lines[key_positions[key]] = rendered
        else:
            lines.append(rendered)

    log(f"write {relpath(target)}")
    if dry_run:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n")


def apply_template_file(
    target: Path,
    template: Path,
    *,
    dry_run: bool,
    replace_existing: bool = False,
) -> None:
    if target.exists() and not replace_existing:
        return
    if not template.exists():
        fail(f"Template not found: {template}")

    action = "reset" if replace_existing and target.exists() else "create"
    log(f"{action} {relpath(target)} from {relpath(template)}")
    if dry_run:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, target)


def detect_host_hostname() -> str:
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["scutil", "--get", "ComputerName"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except OSError:
            pass
    return socket.gethostname()


def generate_secret(existing: str | None, *, preserve_existing: bool) -> str:
    if preserve_existing and not is_blank(existing) and not is_sensitive_placeholder(existing):
        return existing or ""
    return secrets.token_hex(32)


def generate_session_secret(existing: str | None, *, preserve_existing: bool) -> str:
    if preserve_existing and not is_blank(existing) and not is_sensitive_placeholder(existing):
        return existing or ""
    return secrets.token_urlsafe(32)


def nested_get(mapping: dict[str, object], *keys: str) -> object | None:
    current: object = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def build_ushadow_env(config: dict[str, str], existing_env: dict[str, str]) -> dict[str, str]:
    env_name = config.get("USHADOW_ENV_NAME", "ushadow")
    port_offset = int(config.get("USHADOW_PORT_OFFSET", "10"))
    backend_port = 8000 + port_offset
    webui_port = 3000 + port_offset
    redis_db = (port_offset // 10) % 16

    if env_name == "ushadow":
        compose_project_name = "ushadow"
        mongodb_database = "ushadow"
    else:
        compose_project_name = f"ushadow-{env_name.lower()}"
        mongodb_database = f"ushadow_{env_name}"

    return {
        "ENV_NAME": env_name,
        "COMPOSE_PROJECT_NAME": compose_project_name,
        "HOST_HOSTNAME": detect_host_hostname(),
        "PORT_OFFSET": str(port_offset),
        "BACKEND_PORT": str(backend_port),
        "WEBUI_PORT": str(webui_port),
        "MONGODB_DATABASE": mongodb_database,
        "REDIS_DATABASE": str(redis_db),
        "CORS_ORIGINS": (
            f"http://localhost:{webui_port},http://127.0.0.1:{webui_port},"
            f"http://localhost:{backend_port},http://127.0.0.1:{backend_port}"
        ),
        "VITE_BACKEND_URL": f"http://localhost:{backend_port}",
        "VITE_ENV_NAME": env_name,
        "HOST_IP": config.get("USHADOW_HOST_IP", "localhost"),
        "DEV_MODE": "true" if is_truthy(config.get("USHADOW_DEV_MODE"), True) else "false",
        "POSTGRES_USER": config.get("USHADOW_POSTGRES_USER", "ushadow"),
        "POSTGRES_PASSWORD": config.get("USHADOW_POSTGRES_PASSWORD", "ushadow"),
        "POSTGRES_DB": config.get("USHADOW_POSTGRES_DB", "ushadow"),
        "POSTGRES_MULTIPLE_DATABASES": config.get(
            "USHADOW_POSTGRES_MULTIPLE_DATABASES", "metamcp,openmemory"
        ),
        "NEO4J_USERNAME": config.get("USHADOW_NEO4J_USERNAME", "neo4j"),
        "NEO4J_PASSWORD": config.get("USHADOW_NEO4J_PASSWORD", "password"),
        "KC_URL": "http://keycloak:8080",
        "KC_HOSTNAME_URL": config.get("USHADOW_KC_HOSTNAME_URL", "http://localhost:8081"),
        "KC_MOBILE_URL": config.get("USHADOW_KC_MOBILE_URL", ""),
        "KC_REALM": config.get("USHADOW_KC_REALM", "ushadow"),
        "KC_FRONTEND_CLIENT_ID": config.get(
            "USHADOW_KC_FRONTEND_CLIENT_ID", "ushadow-frontend"
        ),
        "KC_BACKEND_CLIENT_ID": config.get(
            "USHADOW_KC_BACKEND_CLIENT_ID", "ushadow-backend"
        ),
        "KC_CLIENT_SECRET": config.get("USHADOW_KC_CLIENT_SECRET", ""),
        "KC_BOOTSTRAP_ADMIN_USERNAME": config.get(
            "USHADOW_KC_BOOTSTRAP_ADMIN_USERNAME", "admin"
        ),
        "KC_BOOTSTRAP_ADMIN_PASSWORD": config.get(
            "USHADOW_KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"
        ),
        "KC_PORT": config.get("USHADOW_KC_PORT", "8081"),
        "KC_MGMT_PORT": config.get("USHADOW_KC_MGMT_PORT", "9000"),
        "SHARE_VALIDATE_RESOURCES": existing_env.get("SHARE_VALIDATE_RESOURCES", "false"),
        "SHARE_VALIDATE_TAILSCALE": existing_env.get("SHARE_VALIDATE_TAILSCALE", "false"),
    }


def write_yaml_block(data: dict[str, object], indent: int = 0) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.extend(write_yaml_block(value, indent + 2))
        else:
            if value is None:
                rendered = "null"
            else:
                rendered = str(value)
                if rendered == "":
                    rendered = '""'
            lines.append(f"{prefix}{key}: {rendered}")
    return lines


def write_ushadow_secrets(
    target: Path,
    config: dict[str, str],
    *,
    dry_run: bool = False,
    mode: str = "keep",
) -> None:
    existing: dict[str, object] = {}
    if target.exists():
        try:
            existing = load_simple_yaml(target)
        except ValueError:
            log(f"skip parsing existing {relpath(target)}; writing merged values")

    preserve_existing = mode == "keep"
    security_existing = existing.get("security", {}) if isinstance(existing.get("security"), dict) else {}
    admin_existing = existing.get("admin", {}) if isinstance(existing.get("admin"), dict) else {}
    api_keys_existing = existing.get("api_keys", {}) if isinstance(existing.get("api_keys"), dict) else {}
    services_existing = existing.get("services", {}) if isinstance(existing.get("services"), dict) else {}

    def choose_value(existing_value: object | None, desired: str) -> str:
        existing_str = str(existing_value) if existing_value is not None else ""
        if preserve_existing and not is_blank(existing_str) and not is_sensitive_placeholder(existing_str):
            return existing_str
        return desired

    payload = {
        "security": {
            "auth_secret_key": generate_session_secret(
                str(security_existing.get("auth_secret_key", "")),
                preserve_existing=preserve_existing,
            ),
            "session_secret": generate_session_secret(
                str(security_existing.get("session_secret", "")),
                preserve_existing=preserve_existing,
            ),
        },
        "api_keys": {
            "openai": choose_value(api_keys_existing.get("openai"), config.get("OPENAI_API_KEY", "")),
            "anthropic": choose_value(
                api_keys_existing.get("anthropic"), config.get("ANTHROPIC_API_KEY", "")
            ),
            "deepgram": choose_value(
                api_keys_existing.get("deepgram"), config.get("DEEPGRAM_API_KEY", "")
            ),
            "mistral": choose_value(
                api_keys_existing.get("mistral"), config.get("MISTRAL_API_KEY", "")
            ),
            "pieces": choose_value(api_keys_existing.get("pieces"), ""),
        },
        "services": {
            "openmemory": {
                "api_key": choose_value(nested_get(services_existing, "openmemory", "api_key"), "")
            },
            "chronicle": {
                "api_key": choose_value(nested_get(services_existing, "chronicle", "api_key"), "")
            },
        },
        "admin": {
            "email": choose_value(admin_existing.get("email"), config.get("ADMIN_EMAIL", "admin@example.com")),
            "name": choose_value(admin_existing.get("name"), "admin"),
            "password": choose_value(admin_existing.get("password"), config.get("ADMIN_PASSWORD", "")),
        },
    }

    lines = [
        "# Ushadow Secrets",
        "# DO NOT COMMIT - Contains sensitive credentials",
        "",
        *write_yaml_block(payload),
        "",
    ]
    if target.exists() and mode == "override":
        log(f"reset {relpath(target)}")
    elif not target.exists():
        log(f"create {relpath(target)}")

    log(f"write {relpath(target)}")
    if dry_run:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines))
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass


def load_simple_yaml(path: Path) -> dict[str, object]:
    """
    Minimal YAML reader for the secrets structure we generate.

    Supports only nested mappings with indentation in multiples of 2.
    """

    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, root)]
    for raw_line in path.read_text().splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped:
            raise ValueError(f"Unsupported YAML line: {raw_line}")

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        if value == "":
            child: dict[str, object] = {}
            current[key] = child
            stack.append((indent, child))
        else:
            if value == '""':
                parsed: object = ""
            elif value == "null":
                parsed = None
            else:
                parsed = value
            current[key] = parsed

    return root


def maybe_bootstrap_config(config_path: Path, dry_run: bool) -> bool:
    if config_path.exists():
        return False

    if not CONFIG_TEMPLATE.exists():
        fail(f"Missing template: {CONFIG_TEMPLATE}")

    log(f"create {relpath(config_path)} from {relpath(CONFIG_TEMPLATE)}")
    if not dry_run:
        shutil.copy2(CONFIG_TEMPLATE, config_path)
    return True


def prompt_shared_config(
    config_path: Path,
    config: dict[str, str],
    *,
    projects: list[str],
    interactive: bool,
    dry_run: bool,
    created: bool,
) -> dict[str, str]:
    log("")
    log("Shared setup config")
    if created:
        log("  `.setup.env` was created from the template.")

    prompts = [
        ("ADMIN_EMAIL", "Admin email", False, "admin@example.com", "shared admin login"),
        ("ADMIN_PASSWORD", "Admin password", True, "", "shared admin password"),
    ]

    if "chronicle" in projects:
        prompts.extend(
            [
                ("OPENAI_API_KEY", "OpenAI API key", True, "", "required for Chronicle default LLM"),
                ("DEEPGRAM_API_KEY", "Deepgram API key", True, "", "required for Chronicle default STT"),
                ("HF_TOKEN", "Hugging Face token", True, "", "optional, enables speaker recognition"),
            ]
        )

    updates: dict[str, str] = {}
    for key, label, secret, default, note in prompts:
        current = config.get(key, "")
        if not interactive and not is_blank(current):
            continue
        if not interactive and is_blank(current):
            continue

        updates[key] = prompt_text(
            label,
            current,
            interactive=interactive,
            secret=secret,
            default=default,
            note=note,
        )

    if updates:
        merged = dict(config)
        merged.update(updates)
        upsert_env_file(config_path, merged, dry_run=dry_run)
        return merged

    return config


def configure_mycelia(config: dict[str, str], dry_run: bool, mode: str) -> None:
    project_root = ROOT / "mycelia"
    env_file = project_root / ".env"
    env_template = project_root / ".env.example"
    existing_env = load_env_file(env_file) if env_file.exists() else {}

    desired_updates = {
        "MYCELIA_URL": config.get("MYCELIA_URL", "https://localhost:4433"),
        "MYCELIA_FRONTEND_HOST": config.get(
            "MYCELIA_FRONTEND_HOST", config.get("MYCELIA_URL", "https://localhost:4433")
        ),
        "NGINX_PORT": config.get("MYCELIA_NGINX_PORT", "4433"),
        "SECRET_KEY": generate_secret(
            existing_env.get("SECRET_KEY"),
            preserve_existing=(mode == "keep"),
        ),
        "MONGO_INITDB_ROOT_USERNAME": config.get(
            "MYCELIA_MONGO_INITDB_ROOT_USERNAME", "root"
        ),
        "MONGO_INITDB_ROOT_PASSWORD": config.get(
            "MYCELIA_MONGO_INITDB_ROOT_PASSWORD", "password"
        ),
        "REDIS_PASSWORD": config.get("MYCELIA_REDIS_PASSWORD", "password"),
    }
    if config.get("HF_TOKEN"):
        desired_updates["HF_TOKEN"] = config["HF_TOKEN"]

    updates = merge_env_updates(existing_env, desired_updates, mode=mode)
    upsert_env_file(
        env_file,
        updates,
        template=env_template,
        dry_run=dry_run,
        replace_existing=(mode == "override"),
    )


def configure_chronicle(config: dict[str, str], dry_run: bool, mode: str) -> None:
    project_root = ROOT / "chronicle"
    root_env = project_root / ".env"
    root_env_template = project_root / ".env.template"
    config_env = project_root / "config.env"
    config_env_template = project_root / "config.env.template"
    config_yml = project_root / "config" / "config.yml"
    config_yml_template = project_root / "config" / "config.yml.template"
    plugins_yml = project_root / "config" / "plugins.yml"
    plugins_yml_template = project_root / "config" / "plugins.yml.template"
    backend_env = project_root / "backends" / "advanced" / ".env"
    backend_env_template = project_root / "backends" / "advanced" / ".env.template"

    if mode == "override":
        apply_template_file(
            config_yml,
            config_yml_template,
            dry_run=dry_run,
            replace_existing=True,
        )
        apply_template_file(
            plugins_yml,
            plugins_yml_template,
            dry_run=dry_run,
            replace_existing=True,
        )
    else:
        apply_template_file(config_yml, config_yml_template, dry_run=dry_run)
        apply_template_file(plugins_yml, plugins_yml_template, dry_run=dry_run)

    root_existing = load_env_file(root_env) if root_env.exists() else {}
    config_existing = load_env_file(config_env) if config_env.exists() else {}
    backend_existing = load_env_file(backend_env) if backend_env.exists() else {}

    common_desired = {
        "DOMAIN": config.get("CHRONICLE_DOMAIN", "localhost"),
        "DEPLOYMENT_MODE": config.get("CHRONICLE_DEPLOYMENT_MODE", "docker-compose"),
        "AUTH_SECRET_KEY": generate_secret(
            backend_existing.get("AUTH_SECRET_KEY"),
            preserve_existing=(mode == "keep"),
        ),
        "ADMIN_EMAIL": config.get("ADMIN_EMAIL", "admin@example.com"),
        "ADMIN_PASSWORD": config.get("ADMIN_PASSWORD", "change-me-please"),
        "OPENAI_API_KEY": config.get("OPENAI_API_KEY", ""),
        "OPENAI_MODEL": config.get("CHRONICLE_OPENAI_MODEL", "gpt-4o-mini"),
        "DEEPGRAM_API_KEY": config.get("DEEPGRAM_API_KEY", ""),
        "HF_TOKEN": config.get("HF_TOKEN", ""),
    }

    upsert_env_file(
        root_env,
        merge_env_updates(root_existing, common_desired, mode=mode),
        template=root_env_template,
        dry_run=dry_run,
        replace_existing=(mode == "override"),
    )
    upsert_env_file(
        config_env,
        merge_env_updates(config_existing, common_desired, mode=mode),
        template=config_env_template,
        dry_run=dry_run,
        replace_existing=(mode == "override"),
    )

    backend_desired = {
        "AUTH_SECRET_KEY": common_desired["AUTH_SECRET_KEY"],
        "ADMIN_EMAIL": common_desired["ADMIN_EMAIL"],
        "ADMIN_PASSWORD": common_desired["ADMIN_PASSWORD"],
        "OPENAI_API_KEY": common_desired["OPENAI_API_KEY"],
        "DEEPGRAM_API_KEY": common_desired["DEEPGRAM_API_KEY"],
        "HF_TOKEN": common_desired["HF_TOKEN"],
    }
    upsert_env_file(
        backend_env,
        merge_env_updates(backend_existing, backend_desired, mode=mode),
        template=backend_env_template,
        dry_run=dry_run,
        replace_existing=(mode == "override"),
    )

    if config.get("HF_TOKEN"):
        speaker_env = project_root / "extras" / "speaker-recognition" / ".env"
        speaker_template = (
            project_root / "extras" / "speaker-recognition" / ".env.template"
        )
        speaker_existing = load_env_file(speaker_env) if speaker_env.exists() else {}
        speaker_desired = {
            "HF_TOKEN": config["HF_TOKEN"],
            "DEEPGRAM_API_KEY": config.get("DEEPGRAM_API_KEY", ""),
        }
        upsert_env_file(
            speaker_env,
            merge_env_updates(speaker_existing, speaker_desired, mode=mode),
            template=speaker_template,
            dry_run=dry_run,
            replace_existing=(mode == "override"),
        )


def configure_ushadow(config: dict[str, str], dry_run: bool, mode: str) -> None:
    project_root = ROOT / "ushadow"
    env_file = project_root / ".env"
    env_template = project_root / ".env.example"

    existing_env = load_env_file(env_file) if env_file.exists() else {}
    desired_updates = build_ushadow_env(config, existing_env)
    updates = merge_env_updates(existing_env, desired_updates, mode=mode)
    upsert_env_file(
        env_file,
        updates,
        template=env_template,
        dry_run=dry_run,
        replace_existing=(mode == "override"),
    )

    secrets_file = project_root / "config" / "SECRETS" / "secrets.yaml"
    write_ushadow_secrets(secrets_file, config, dry_run=dry_run, mode=mode)


def ensure_projects_exist(projects: list[str]) -> None:
    missing = [name for name in projects if not (ROOT / name).exists()]
    if missing:
        names = ", ".join(missing)
        fail(
            f"Missing subrepositories: {names}. Run `git submodule update --init --recursive` first."
        )


def run_command(command: list[str], cwd: Path, dry_run: bool) -> None:
    rendered = " ".join(command)
    log(f"run ({relpath(cwd)}): {rendered}")
    if dry_run:
        return
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode != 0:
        fail(f"Command failed in {cwd}: {rendered}")


def maybe_start_projects(
    projects: list[str],
    config: dict[str, str],
    *,
    dry_run: bool,
) -> None:
    for project in projects:
        if project == "mycelia":
            run_command(
                ["docker", "compose", "-f", "docker-compose.yml", "up", "-d"],
                ROOT / "mycelia",
                dry_run,
            )
        elif project == "chronicle":
            run_command(["bash", "./start.sh", "--build"], ROOT / "chronicle", dry_run)
        elif project == "ushadow":
            dev_mode = is_truthy(config.get("USHADOW_DEV_MODE"), True)
            command = ["python3", "setup/run.py", "--build"]
            command.append("--dev" if dev_mode else "--prod")
            run_command(command, ROOT / "ushadow", dry_run)


def collect_mycelia_status() -> ProjectStatus:
    env_file = ROOT / "mycelia" / ".env"
    existing_files: list[str] = []
    missing_files: list[str] = []
    missing_values: list[str] = []
    notes: list[str] = []

    if env_file.exists():
        existing_files.append(relpath(env_file))
        env = load_env_file(env_file)
        required_checks = [
            ("MYCELIA_URL", False),
            ("MYCELIA_FRONTEND_HOST", False),
            ("NGINX_PORT", False),
            ("SECRET_KEY", True),
            ("MONGO_INITDB_ROOT_USERNAME", False),
            ("MONGO_INITDB_ROOT_PASSWORD", False),
            ("REDIS_PASSWORD", False),
        ]
        for key, reject_placeholders in required_checks:
            if not has_required_value(env, key, reject_placeholders=reject_placeholders):
                missing_values.append(key)

        if not has_required_value(env, "MYCELIA_CLIENT_ID", reject_placeholders=True) or not has_required_value(
            env, "MYCELIA_TOKEN", reject_placeholders=True
        ):
            notes.append(
                "CLI tokens are not generated yet (`MYCELIA_CLIENT_ID` / `MYCELIA_TOKEN`)."
            )
    else:
        missing_files.append(relpath(env_file))

    state = "configured"
    if not existing_files:
        state = "not_setup"
    elif missing_files or missing_values:
        state = "partial"

    return ProjectStatus(
        name="mycelia",
        state=state,
        existing_files=existing_files,
        missing_files=missing_files,
        missing_values=missing_values,
        notes=notes,
    )


def collect_chronicle_status() -> ProjectStatus:
    project_root = ROOT / "chronicle"
    required_files = [
        project_root / "config" / "config.yml",
        project_root / "config" / "plugins.yml",
        project_root / ".env",
        project_root / "config.env",
        project_root / "backends" / "advanced" / ".env",
    ]
    existing_files: list[str] = []
    missing_files: list[str] = []
    missing_values: list[str] = []
    notes: list[str] = []

    for path in required_files:
        if path.exists():
            existing_files.append(relpath(path))
        else:
            missing_files.append(relpath(path))

    backend_env = project_root / "backends" / "advanced" / ".env"
    if backend_env.exists():
        env = load_env_file(backend_env)
        required_checks = [
            ("AUTH_SECRET_KEY", True),
            ("ADMIN_EMAIL", False),
            ("ADMIN_PASSWORD", True),
            ("OPENAI_API_KEY", True),
            ("DEEPGRAM_API_KEY", True),
        ]
        for key, reject_placeholders in required_checks:
            if not has_required_value(env, key, reject_placeholders=reject_placeholders):
                missing_values.append(key)
        if not has_required_value(env, "HF_TOKEN", reject_placeholders=True):
            notes.append("Speaker recognition is optional and not configured yet (`HF_TOKEN`).")

    state = "configured"
    if not existing_files:
        state = "not_setup"
    elif missing_files or missing_values:
        state = "partial"

    return ProjectStatus(
        name="chronicle",
        state=state,
        existing_files=existing_files,
        missing_files=missing_files,
        missing_values=missing_values,
        notes=notes,
    )


def collect_ushadow_status() -> ProjectStatus:
    project_root = ROOT / "ushadow"
    env_file = project_root / ".env"
    secrets_file = project_root / "config" / "SECRETS" / "secrets.yaml"
    existing_files: list[str] = []
    missing_files: list[str] = []
    missing_values: list[str] = []
    notes: list[str] = []

    if env_file.exists():
        existing_files.append(relpath(env_file))
        env = load_env_file(env_file)
        for key in ("ENV_NAME", "BACKEND_PORT", "WEBUI_PORT", "MONGODB_DATABASE", "KC_REALM"):
            if not has_required_value(env, key):
                missing_values.append(key)
    else:
        missing_files.append(relpath(env_file))

    if secrets_file.exists():
        existing_files.append(relpath(secrets_file))
        try:
            secrets_data = load_simple_yaml(secrets_file)
            auth_secret = nested_get(secrets_data, "security", "auth_secret_key")
            session_secret = nested_get(secrets_data, "security", "session_secret")
            if is_blank(str(auth_secret) if auth_secret is not None else ""):
                missing_values.append("security.auth_secret_key")
            if is_blank(str(session_secret) if session_secret is not None else ""):
                missing_values.append("security.session_secret")
            admin_password = nested_get(secrets_data, "admin", "password")
            if is_blank(str(admin_password) if admin_password is not None else ""):
                notes.append("Admin password is not stored yet; you can still register via the UI.")
        except ValueError:
            missing_values.append("config/SECRETS/secrets.yaml (unreadable)")
    else:
        missing_files.append(relpath(secrets_file))

    state = "configured"
    if not existing_files:
        state = "not_setup"
    elif missing_files or missing_values:
        state = "partial"

    return ProjectStatus(
        name="ushadow",
        state=state,
        existing_files=existing_files,
        missing_files=missing_files,
        missing_values=missing_values,
        notes=notes,
    )


def collect_project_statuses(projects: list[str]) -> list[ProjectStatus]:
    statuses: list[ProjectStatus] = []
    for project in projects:
        if project == "mycelia":
            statuses.append(collect_mycelia_status())
        elif project == "chronicle":
            statuses.append(collect_chronicle_status())
        elif project == "ushadow":
            statuses.append(collect_ushadow_status())
    return statuses


def print_status_report(title: str, statuses: list[ProjectStatus]) -> None:
    log("")
    log(title)
    for status in statuses:
        log(f"- {status.name}: {status.state}")
        if status.existing_files:
            log(f"  existing: {', '.join(status.existing_files)}")
        if status.missing_files:
            log(f"  missing files: {', '.join(status.missing_files)}")
        if status.missing_values:
            log(f"  missing values: {', '.join(status.missing_values)}")
        for note in status.notes:
            log(f"  note: {note}")


def print_summary(config_path: Path, statuses: list[ProjectStatus]) -> None:
    log("")
    log("Shared config")
    log(f"  file: {relpath(config_path)}")
    log("")
    log("Database locations")
    log("  - Mycelia MongoDB: Docker volume `mongo_data` unless `MONGO_HOST_PATH` is set")
    log("  - Mycelia Redis: Docker volume `redis_data` unless `REDIS_HOST_PATH` is set")
    log("  - Chronicle MongoDB: Docker volume `mongo_data` from `chronicle/backends/advanced/docker-compose.yml`")
    log("  - Chronicle Qdrant: `chronicle/backends/advanced/data/qdrant_data`")
    log("  - Chronicle Redis: `chronicle/backends/advanced/data/redis_data`")
    log("  - Ushadow Mongo/Redis/Qdrant/Postgres: Docker volumes `mongo_data`, `redis_data`, `qdrant_data`, `postgres_data`")
    log("")
    log("Where secrets end up")
    log("  - Shared editable source: `.setup.env`")
    log("  - Mycelia runtime env: `mycelia/.env`")
    log("  - Chronicle runtime env: `chronicle/backends/advanced/.env`")
    log("  - Ushadow runtime env: `ushadow/.env`")
    log("  - Ushadow generated secrets: `ushadow/config/SECRETS/secrets.yaml`")
    log("")
    log("External keys you usually need to bring yourself")
    log("  - OpenAI: https://platform.openai.com/api-keys")
    log("  - Deepgram: https://console.deepgram.com/")
    log("  - Hugging Face: https://huggingface.co/settings/tokens")
    log("")
    log("Remaining setup work")
    pending = False
    for status in statuses:
        if status.state == "configured":
            continue
        pending = True
        log(f"  - {status.name}: still {status.state}")
        if status.missing_files:
            log(f"    files: {', '.join(status.missing_files)}")
        if status.missing_values:
            log(f"    values: {', '.join(status.missing_values)}")
    if not pending:
        log("  - all selected projects look configured")


def parse_projects(raw: str) -> list[str]:
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    if not requested or requested == ["all"]:
        return ["mycelia", "chronicle", "ushadow"]

    allowed = {"mycelia", "chronicle", "ushadow"}
    unknown = [item for item in requested if item not in allowed]
    if unknown:
        fail(f"Unknown project selection: {', '.join(unknown)}")
    return requested


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified setup for all subprojects")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to the shared setup env file (default: .setup.env)",
    )
    parser.add_argument(
        "--projects",
        default="all",
        help="Comma-separated list: mycelia,chronicle,ushadow or all",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the configured projects after writing config files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without writing files or starting services",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Only show setup status for the selected projects",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Never prompt; keep existing files and only fill missing values",
    )
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="Overwrite generated runtime files when they already exist",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Keep existing runtime files and only fill missing values",
    )
    args = parser.parse_args()

    if args.overwrite_existing and args.keep_existing:
        fail("Use only one of --overwrite-existing or --keep-existing.")

    config_path = Path(args.config).resolve()
    if not str(config_path).startswith(str(ROOT)):
        fail("The config file must live inside this repository.")

    interactive = (
        sys.stdin.isatty()
        and not args.non_interactive
        and not args.dry_run
        and not args.status_only
    )

    created_config = maybe_bootstrap_config(config_path, args.dry_run)
    config = load_env_file(config_path)
    projects = parse_projects(args.projects)
    ensure_projects_exist(projects)

    config = prompt_shared_config(
        config_path,
        config,
        projects=projects,
        interactive=interactive,
        dry_run=args.dry_run,
        created=created_config,
    )

    current_statuses = collect_project_statuses(projects)
    print_status_report("Current project status", current_statuses)

    if args.status_only:
        print_summary(config_path, current_statuses)
        return

    statuses_by_project = {status.name: status for status in current_statuses}
    project_modes = {
        project: choose_existing_mode(
            project,
            statuses_by_project[project].existing_files,
            interactive=interactive,
            overwrite_existing=args.overwrite_existing,
            keep_existing=args.keep_existing,
        )
        for project in projects
    }

    if "mycelia" in projects:
        configure_mycelia(config, args.dry_run, project_modes["mycelia"])
    if "chronicle" in projects:
        configure_chronicle(config, args.dry_run, project_modes["chronicle"])
    if "ushadow" in projects:
        configure_ushadow(config, args.dry_run, project_modes["ushadow"])

    final_statuses = collect_project_statuses(projects)
    print_status_report("Final project status", final_statuses)

    if args.start:
        maybe_start_projects(projects, config, dry_run=args.dry_run)

    print_summary(config_path, final_statuses)


if __name__ == "__main__":
    main()
