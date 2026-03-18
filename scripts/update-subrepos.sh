#!/usr/bin/env bash

set -u

SCRIPT_DIR=$(
  CDPATH= cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd
)
REPO_ROOT=$(
  CDPATH= cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd
)

DRY_RUN=0
ROOT_ONLY=0
FAILED=0

usage() {
  cat <<'EOF'
Usage: ./scripts/update-subrepos.sh [--dry-run] [--root-only]

Updates this meta-repo's child repositories in a repo-aware way.

Options:
  --dry-run    Print the commands that would run without changing anything
  --root-only  Update only the top-level child repos tracked by this repo
  -h, --help   Show this help text
EOF
}

log() {
  printf '[update-subrepos] %s\n' "$*"
}

warn() {
  printf '[update-subrepos] warning: %s\n' "$*" >&2
}

run() {
  if [ "${DRY_RUN}" -eq 1 ]; then
    printf '[update-subrepos] dry-run:'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi

  "$@"
}

canonical_path() {
  (
    CDPATH= cd -- "$1" >/dev/null 2>&1 && pwd -P
  )
}

is_repo_root() {
  local path
  local actual_root
  local expected_root

  path="$1"

  [ -d "${path}" ] || return 1

  expected_root=$(canonical_path "${path}") || return 1
  actual_root=$(git -C "${path}" rev-parse --show-toplevel 2>/dev/null) || return 1

  [ "${expected_root}" = "${actual_root}" ]
}

declared_submodule_paths() {
  local parent

  parent="$1"

  [ -f "${parent}/.gitmodules" ] || return 0

  git -C "${parent}" config --file .gitmodules --get-regexp '^submodule\..*\.path$' 2>/dev/null \
    | awk '{ print $2 }'
}

gitlink_paths() {
  local parent

  parent="$1"

  git -C "${parent}" ls-tree -d HEAD 2>/dev/null | awk '$1 == "160000" { print $4 }'
}

path_in_list() {
  local needle
  local item

  needle="$1"
  shift

  for item in "$@"; do
    [ "${item}" = "${needle}" ] && return 0
  done

  return 1
}

is_clean_repo() {
  local path

  path="$1"

  [ -z "$(git -C "${path}" status --porcelain 2>/dev/null)" ]
}

ensure_initialized() {
  local parent
  local rel_path
  local label
  local full_path

  parent="$1"
  rel_path="$2"
  label="$3"
  full_path="${parent}/${rel_path}"

  if is_repo_root "${full_path}"; then
    return 0
  fi

  log "Initializing ${label}"
  if ! run git -C "${parent}" submodule update --init "${rel_path}"; then
    warn "Failed to initialize ${label}"
    FAILED=1
    return 1
  fi

  if [ "${DRY_RUN}" -eq 1 ]; then
    return 0
  fi

  if ! is_repo_root "${full_path}"; then
    warn "${label} is still not checked out as its own git repo"
    FAILED=1
    return 1
  fi
}

attach_default_branch() {
  local path
  local label
  local default_ref
  local default_branch

  path="$1"
  label="$2"

  default_ref=$(git -C "${path}" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)
  default_branch=${default_ref#origin/}

  if [ -z "${default_branch}" ] && [ "${DRY_RUN}" -eq 0 ]; then
    log "Fetching origin for ${label} to determine the default branch"
    if ! run git -C "${path}" fetch origin; then
      warn "Failed to fetch origin for ${label}"
      FAILED=1
      return 1
    fi
    default_ref=$(git -C "${path}" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)
    default_branch=${default_ref#origin/}
  fi

  if [ -z "${default_branch}" ]; then
    warn "Skipping ${label}: detached HEAD and origin/HEAD is unknown"
    FAILED=1
    return 1
  fi

  log "Attaching ${label} to ${default_branch}"
  if git -C "${path}" show-ref --verify --quiet "refs/heads/${default_branch}"; then
    run git -C "${path}" checkout "${default_branch}" || {
      warn "Failed to checkout ${default_branch} in ${label}"
      FAILED=1
      return 1
    }
  else
    run git -C "${path}" checkout -b "${default_branch}" --track "origin/${default_branch}" || {
      warn "Failed to create ${default_branch} in ${label}"
      FAILED=1
      return 1
    }
  fi
}

update_repo() {
  local path
  local label
  local branch

  path="$1"
  label="$2"

  if ! is_repo_root "${path}"; then
    warn "Skipping ${label}: ${path} is not checked out as its own git repo"
    FAILED=1
    return 1
  fi

  if ! is_clean_repo "${path}"; then
    warn "Skipping ${label}: local changes are present"
    FAILED=1
    return 1
  fi

  branch=$(git -C "${path}" symbolic-ref --quiet --short HEAD 2>/dev/null || true)
  if [ -z "${branch}" ]; then
    attach_default_branch "${path}" "${label}" || return 1
    branch=$(git -C "${path}" symbolic-ref --quiet --short HEAD 2>/dev/null || true)
    if [ -z "${branch}" ] && [ "${DRY_RUN}" -eq 1 ]; then
      branch="<origin-default>"
    fi
  fi

  log "Updating ${label} on ${branch}"
  if ! run git -C "${path}" pull --ff-only; then
    warn "Failed to update ${label}"
    FAILED=1
    return 1
  fi
}

process_declared_repo() {
  local parent
  local rel_path
  local label

  parent="$1"
  rel_path="$2"
  label="$3"

  ensure_initialized "${parent}" "${rel_path}" "${label}" || return 1

  if [ "${DRY_RUN}" -eq 1 ] && ! is_repo_root "${parent}/${rel_path}"; then
    log "Would update ${label} after initialization"
    return 0
  fi

  update_repo "${parent}/${rel_path}" "${label}"
}

update_declared_submodules() {
  local parent
  local prefix
  local paths
  local path

  parent="$1"
  prefix="$2"
  paths=$(declared_submodule_paths "${parent}")

  for path in ${paths}; do
    process_declared_repo "${parent}" "${path}" "${prefix}${path}"
  done
}

handle_undeclared_gitlinks() {
  local parent
  local prefix
  local declared_paths
  local gitlink_list
  local gitlink

  parent="$1"
  prefix="$2"
  declared_paths=$(declared_submodule_paths "${parent}")
  gitlink_list=$(gitlink_paths "${parent}")

  for gitlink in ${gitlink_list}; do
    if path_in_list "${gitlink}" ${declared_paths}; then
      continue
    fi

    if is_repo_root "${parent}/${gitlink}"; then
      warn "${prefix}${gitlink} is not declared in ${parent}/.gitmodules; updating it as a standalone checkout"
      update_repo "${parent}/${gitlink}" "${prefix}${gitlink}"
      continue
    fi

    warn "${prefix}${gitlink} exists as a gitlink in ${parent}, but it is not declared in ${parent}/.gitmodules so it cannot be initialized automatically"
  done
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --root-only)
      ROOT_ONLY=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if ! git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  warn "Could not find the repo root from ${REPO_ROOT}"
  exit 1
fi

log "Repo root: ${REPO_ROOT}"
log "Updating top-level child repos"
update_declared_submodules "${REPO_ROOT}" ""

if [ "${ROOT_ONLY}" -eq 0 ]; then
  if is_repo_root "${REPO_ROOT}/ushadow"; then
    log "Updating child repos declared inside ushadow"
    update_declared_submodules "${REPO_ROOT}/ushadow" "ushadow/"
    handle_undeclared_gitlinks "${REPO_ROOT}/ushadow" "ushadow/"
  else
    warn "Skipping nested ushadow repos because ushadow is not initialized"
  fi
fi

log "Review parent repo status before committing:"
log "  git status"
log "  git -C ushadow status"

exit "${FAILED}"
