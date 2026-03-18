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
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / ".setup.env"
CONFIG_TEMPLATE = ROOT / ".setup.env.example"
ENV_KEY_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def log(message: str) -> None:
    print(message)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


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


def is_blank_or_placeholder(value: str | None) -> bool:
    if value is None:
        return True

    normalized = value.strip()
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
        "password",
        "admin@example.com",
        "your-openai-key-here",
        "your-deepgram-key-here",
        "your-huggingface-token-here",
        "your-super-secret-jwt-key-here-make-it-random-and-long",
    }
    lowered = normalized.lower()
    return lowered in placeholder_values or lowered.startswith(placeholder_prefixes)


def ensure_from_template(target: Path, template: Path, dry_run: bool) -> None:
    if target.exists():
        return
    if not template.exists():
        fail(f"Template not found: {template}")

    log(f"create {target.relative_to(ROOT)} from {template.relative_to(ROOT)}")
    if dry_run:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, target)


def upsert_env_file(
    target: Path,
    updates: dict[str, str],
    *,
    template: Path | None = None,
    dry_run: bool = False,
) -> None:
    if template is not None and not target.exists():
        ensure_from_template(target, template, dry_run)

    if target.exists():
        lines = target.read_text().splitlines()
    else:
        lines = []

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

    log(f"write {target.relative_to(ROOT)}")
    if dry_run:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n")


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


def generate_secret(existing: str | None) -> str:
    if existing and not is_blank_or_placeholder(existing):
        return existing
    return secrets.token_hex(32)


def generate_session_secret(existing: str | None) -> str:
    if existing and not is_blank_or_placeholder(existing):
        return existing
    return secrets.token_urlsafe(32)


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
) -> None:
    existing = {}
    if target.exists():
        try:
            existing = load_simple_yaml(target)
        except ValueError:
            log(f"skip parsing existing {target.relative_to(ROOT)}; overwriting with merged values")

    security_existing = existing.get("security", {}) if isinstance(existing.get("security"), dict) else {}
    admin_existing = existing.get("admin", {}) if isinstance(existing.get("admin"), dict) else {}
    api_keys_existing = existing.get("api_keys", {}) if isinstance(existing.get("api_keys"), dict) else {}
    services_existing = existing.get("services", {}) if isinstance(existing.get("services"), dict) else {}

    payload = {
        "security": {
            "auth_secret_key": generate_session_secret(security_existing.get("auth_secret_key")),
            "session_secret": generate_session_secret(security_existing.get("session_secret")),
        },
        "api_keys": {
            "openai": config.get("OPENAI_API_KEY", api_keys_existing.get("openai", "")),
            "anthropic": config.get("ANTHROPIC_API_KEY", api_keys_existing.get("anthropic", "")),
            "deepgram": config.get("DEEPGRAM_API_KEY", api_keys_existing.get("deepgram", "")),
            "mistral": config.get("MISTRAL_API_KEY", api_keys_existing.get("mistral", "")),
            "pieces": api_keys_existing.get("pieces", ""),
        },
        "services": {
            "openmemory": {
                "api_key": (
                    services_existing.get("openmemory", {}).get("api_key", "")
                    if isinstance(services_existing.get("openmemory"), dict)
                    else ""
                )
            },
            "chronicle": {
                "api_key": (
                    services_existing.get("chronicle", {}).get("api_key", "")
                    if isinstance(services_existing.get("chronicle"), dict)
                    else ""
                )
            },
        },
        "admin": {
            "email": config.get("ADMIN_EMAIL", admin_existing.get("email", "admin@example.com")),
            "name": admin_existing.get("name", "admin"),
            "password": config.get("ADMIN_PASSWORD", admin_existing.get("password", "")),
        },
    }

    lines = [
        "# Ushadow Secrets",
        "# DO NOT COMMIT - Contains sensitive credentials",
        "",
        *write_yaml_block(payload),
        "",
    ]
    log(f"write {target.relative_to(ROOT)}")
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


def configure_mycelia(config: dict[str, str], dry_run: bool) -> None:
    project_root = ROOT / "mycelia"
    env_file = project_root / ".env"
    env_template = project_root / ".env.example"
    existing_env = load_env_file(env_file) if env_file.exists() else {}

    updates = {
        "MYCELIA_URL": config.get("MYCELIA_URL", "https://localhost:4433"),
        "MYCELIA_FRONTEND_HOST": config.get(
            "MYCELIA_FRONTEND_HOST", config.get("MYCELIA_URL", "https://localhost:4433")
        ),
        "NGINX_PORT": config.get("MYCELIA_NGINX_PORT", "4433"),
        "SECRET_KEY": generate_secret(existing_env.get("SECRET_KEY")),
        "MONGO_INITDB_ROOT_USERNAME": config.get(
            "MYCELIA_MONGO_INITDB_ROOT_USERNAME", "root"
        ),
        "MONGO_INITDB_ROOT_PASSWORD": config.get(
            "MYCELIA_MONGO_INITDB_ROOT_PASSWORD", "password"
        ),
        "REDIS_PASSWORD": config.get("MYCELIA_REDIS_PASSWORD", "password"),
    }
    if config.get("HF_TOKEN"):
        updates["HF_TOKEN"] = config["HF_TOKEN"]

    upsert_env_file(env_file, updates, template=env_template, dry_run=dry_run)


def configure_chronicle(config: dict[str, str], dry_run: bool) -> None:
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

    ensure_from_template(config_yml, config_yml_template, dry_run)
    ensure_from_template(plugins_yml, plugins_yml_template, dry_run)

    existing_backend_env = load_env_file(backend_env) if backend_env.exists() else {}
    common_updates = {
        "DOMAIN": config.get("CHRONICLE_DOMAIN", "localhost"),
        "DEPLOYMENT_MODE": config.get("CHRONICLE_DEPLOYMENT_MODE", "docker-compose"),
        "AUTH_SECRET_KEY": generate_secret(existing_backend_env.get("AUTH_SECRET_KEY")),
        "ADMIN_EMAIL": config.get("ADMIN_EMAIL", "admin@example.com"),
        "ADMIN_PASSWORD": config.get("ADMIN_PASSWORD", "change-me-please"),
        "OPENAI_API_KEY": config.get("OPENAI_API_KEY", ""),
        "OPENAI_MODEL": config.get("CHRONICLE_OPENAI_MODEL", "gpt-4o-mini"),
        "DEEPGRAM_API_KEY": config.get("DEEPGRAM_API_KEY", ""),
        "HF_TOKEN": config.get("HF_TOKEN", ""),
    }

    upsert_env_file(root_env, common_updates, template=root_env_template, dry_run=dry_run)
    upsert_env_file(
        config_env, common_updates, template=config_env_template, dry_run=dry_run
    )

    backend_updates = {
        "AUTH_SECRET_KEY": common_updates["AUTH_SECRET_KEY"],
        "ADMIN_EMAIL": common_updates["ADMIN_EMAIL"],
        "ADMIN_PASSWORD": common_updates["ADMIN_PASSWORD"],
        "OPENAI_API_KEY": common_updates["OPENAI_API_KEY"],
        "DEEPGRAM_API_KEY": common_updates["DEEPGRAM_API_KEY"],
        "HF_TOKEN": common_updates["HF_TOKEN"],
    }
    upsert_env_file(
        backend_env, backend_updates, template=backend_env_template, dry_run=dry_run
    )

    if config.get("HF_TOKEN"):
        speaker_env = project_root / "extras" / "speaker-recognition" / ".env"
        speaker_template = (
            project_root / "extras" / "speaker-recognition" / ".env.template"
        )
        ensure_from_template(speaker_env, speaker_template, dry_run)
        upsert_env_file(
            speaker_env,
            {
                "HF_TOKEN": config["HF_TOKEN"],
                "DEEPGRAM_API_KEY": config.get("DEEPGRAM_API_KEY", ""),
            },
            template=speaker_template,
            dry_run=dry_run,
        )


def configure_ushadow(config: dict[str, str], dry_run: bool) -> None:
    project_root = ROOT / "ushadow"
    env_file = project_root / ".env"
    env_template = project_root / ".env.example"

    existing_env = load_env_file(env_file) if env_file.exists() else {}
    updates = build_ushadow_env(config, existing_env)
    upsert_env_file(env_file, updates, template=env_template, dry_run=dry_run)

    secrets_file = project_root / "config" / "SECRETS" / "secrets.yaml"
    write_ushadow_secrets(secrets_file, config, dry_run=dry_run)


def ensure_projects_exist(projects: list[str]) -> None:
    missing = [name for name in projects if not (ROOT / name).exists()]
    if missing:
        names = ", ".join(missing)
        fail(
            f"Missing subrepositories: {names}. Run `git submodule update --init --recursive` first."
        )


def run_command(command: list[str], cwd: Path, dry_run: bool) -> None:
    rendered = " ".join(command)
    log(f"run ({cwd.relative_to(ROOT)}): {rendered}")
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


def print_summary(config_path: Path) -> None:
    log("")
    log("Unified setup complete.")
    log(f"Shared config: {config_path.relative_to(ROOT)}")
    log("")
    log("Database locations:")
    log("  - Mycelia MongoDB: Docker volume `mongo_data` unless `MONGO_HOST_PATH` is set")
    log("  - Mycelia Redis: Docker volume `redis_data` unless `REDIS_HOST_PATH` is set")
    log("  - Chronicle MongoDB: Docker volume `mongo_data` from `chronicle/backends/advanced/docker-compose.yml`")
    log("  - Chronicle Qdrant: `chronicle/backends/advanced/data/qdrant_data`")
    log("  - Chronicle Redis: `chronicle/backends/advanced/data/redis_data`")
    log("  - Ushadow Mongo/Redis/Qdrant/Postgres: Docker volumes `mongo_data`, `redis_data`, `qdrant_data`, `postgres_data`")
    log("")
    log("Where secrets end up:")
    log("  - Shared editable source: `.setup.env`")
    log("  - Mycelia runtime env: `mycelia/.env`")
    log("  - Chronicle runtime env: `chronicle/backends/advanced/.env`")
    log("  - Ushadow runtime env: `ushadow/.env`")
    log("  - Ushadow generated secrets: `ushadow/config/SECRETS/secrets.yaml`")
    log("")
    log("External keys you usually need to bring yourself:")
    log("  - OpenAI: https://platform.openai.com/api-keys")
    log("  - Deepgram: https://console.deepgram.com/")
    log("  - Hugging Face: https://huggingface.co/settings/tokens")


def parse_projects(raw: str) -> list[str]:
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    if not requested or requested == ["all"]:
        return ["mycelia", "chronicle", "ushadow"]

    allowed = {"mycelia", "chronicle", "ushadow"}
    unknown = [item for item in requested if item not in allowed]
    if unknown:
        fail(f"Unknown project selection: {', '.join(unknown)}")
    return requested


def maybe_bootstrap_config(config_path: Path, dry_run: bool) -> None:
    if config_path.exists():
        return

    if not CONFIG_TEMPLATE.exists():
        fail(f"Missing template: {CONFIG_TEMPLATE}")

    log(f"create {config_path.relative_to(ROOT)} from {CONFIG_TEMPLATE.relative_to(ROOT)}")
    if dry_run:
        return
    shutil.copy2(CONFIG_TEMPLATE, config_path)
    fail(
        "Created `.setup.env`. Fill in the keys you need, then rerun `./setup.sh`."
    )


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
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    if not str(config_path).startswith(str(ROOT)):
        fail("The config file must live inside this repository.")

    maybe_bootstrap_config(config_path, args.dry_run)

    config = load_env_file(config_path)
    projects = parse_projects(args.projects)
    ensure_projects_exist(projects)

    if "mycelia" in projects:
        configure_mycelia(config, args.dry_run)
    if "chronicle" in projects:
        configure_chronicle(config, args.dry_run)
    if "ushadow" in projects:
        configure_ushadow(config, args.dry_run)

    if args.start:
        maybe_start_projects(projects, config, dry_run=args.dry_run)

    print_summary(config_path)


if __name__ == "__main__":
    main()
