# Self-Hosted Memory Assistants

A meta-repository that ties together four self-hosted AI memory projects via git submodules. Each project captures, processes, and retrieves personal data, memories, or knowledge artifacts, and they can be run side by side through ushadow's batch tooling.

## Projects

### [Mycelia](https://github.com/mycelia-tech/mycelia)

Self-hosted AI memory and timeline system. Captures personal data through voice memos, screenshots, and text, then organizes and retrieves it conversationally. Ask "What did I say about X last May?" and get personalized responses in your own words.

- **Stack:** Deno backend, React/Vite frontend, Python diarizator, MongoDB, Redis
- **Features:** D3.js interactive timeline, AI chat with memory access, audio transcription (Whisper), speaker diarization, object extraction (people, events, promises), full-text search, MCP server

### [Chronicle](https://github.com/chronicler-ai/chronicle)

AI-powered personal memory system for wearable devices. Captures continuous audio streams from OMI devices via WebSocket, transcribes speech, extracts memories using LLMs, and provides a searchable dashboard.

- **Stack:** FastAPI (Python), React dashboard, React Native mobile app, MongoDB, Qdrant
- **Features:** Real-time audio capture (Wyoming protocol), Deepgram/Parakeet transcription, memory extraction, semantic vector search, speaker recognition, job tracking pipeline

### [Exocortex](https://github.com/amaslak0v/exocortex)

Personal knowledge OS built around an Obsidian vault, Claude Code skills, and a lightweight control panel.

- **Stack:** Markdown/Obsidian vault, Claude Code skills and agents, Node/Express control panel
- **Features:** Domain-specific skills, autonomous sync agents, MCP bridge configs, and a local dashboard over the vault

### [ushadow](https://github.com/Ushadow-io/Ushadow)

AI orchestration platform and unified dashboard. Acts as the central hub that integrates Chronicle, MCP services, Agent Zero, n8n workflows, and other services under one roof.

- **Stack:** FastAPI (Python), React frontend, MongoDB, Redis, Qdrant, Keycloak
- **Features:** Multi-service orchestration, Chronicle integration proxy, interactive CLI (`ush`), setup wizard, multi-environment isolation via git worktrees, Kubernetes-ready

## Running the Projects

### Standalone Mode

Each project works independently with its own default startup path and ports:

```bash
cd mycelia && docker compose up -d           # ports 3210, 4433, 27017
cd chronicle/backends/advanced && docker compose up -d  # ports 8000, 3010, 27017, 6379
cd exocortex/control-panel && npm ci && npm start       # port 3333
cd ushadow && docker compose up -d           # ports 8000, 27017, 6379
```

### Combined Mode

To run the batch together, the parent repo provides override files that remap conflicting Docker services, a shared Docker network for cross-module communication, and a helper that runs Exocortex's control panel as a host process. No submodule files are modified.

```bash
npm ci --prefix exocortex/control-panel       # one-time for Exocortex
./start-all.sh up      # start all services
./start-all.sh down    # stop all services
./start-all.sh status  # show running containers
```

Access points in combined mode:

| Service | URL |
|---------|-----|
| Mycelia | http://localhost:3210 |
| Exocortex | http://localhost:3333 |
| Ushadow backend | http://localhost:8010 |
| Chronicle backend | http://localhost:9000 |
| Chronicle UI | http://localhost:9010 |
| OpenMemory UI | http://localhost:9001 |
| OpenMemory API | http://localhost:9765 |

### How Combined Mode Works

Each module gets a unique port range so nothing conflicts:

| Module | Port range | Mongo | Redis | Qdrant | Neo4j | Backend/UI |
|--------|-----------|-------|-------|--------|-------|------------|
| Mycelia | 32xx | 27019 | — | — | — | 3210 |
| Exocortex | 33xx | — | — | — | — | 3333 |
| Ushadow | 80xx | 27020 | 6382 | 6335/6336 | 7476/7689 | 8010 |
| Chronicle | 90xx | 27018 | 6380 | 6033/6034 | 7475/7688 | 9000/9010 |

Each Docker-backed module keeps its own database instances. Exocortex does not ship a Docker Compose stack in this repo, so it runs directly on the host and does not join `memory-net`. The full port map is in [.env.ports](.env.ports).

### Data Sharing via OpenMemory

In combined mode, [OpenMemory MCP](https://github.com/mem0ai/mem0) runs as a shared memory store that all modules can access over the `memory-net` network:

```
Chronicle ──writes memories──→ OpenMemory MCP (Qdrant) ←──queries── Ushadow
                                      ↑
                               memory-net network
                                      ↑
Mycelia ──queryable via REST API──────┘
```

- **Chronicle** automatically writes extracted memories to OpenMemory (configured via `MEMORY_PROVIDER=openmemory_mcp` in the override)
- **Ushadow** aggregates memories from OpenMemory, Chronicle, and Mycelia through its proxy
- **Mycelia** stays read-only for now — its memories are queryable via its API but it doesn't push to OpenMemory
- **Exocortex** currently stays independent from the OpenMemory flow; it coexists cleanly in the batch but is not yet wired into the shared memory graph
- **OpenMemory UI** at http://localhost:9001 provides a unified browse/search interface

OpenMemory requires an `OPENAI_API_KEY` in `chronicle/extras/openmemory-mcp/.env` for memory extraction and embeddings.

**Override files** in the [overrides/](overrides/) directory use Docker Compose's `-f` merge feature to remap ports and add networks without touching submodule files:

```
overrides/
├── chronicle.override.yml           # main chronicle services
├── chronicle-speaker.override.yml   # speaker recognition extra
├── chronicle-openmemory.override.yml # openmemory MCP extra
├── chronicle-langfuse.override.yml  # langfuse extra
├── mycelia.override.yml             # main mycelia services
├── mycelia-gpu.override.yml         # mycelia GPU services
├── ushadow-infra.override.yml       # ushadow infrastructure (mongo, redis, etc.)
└── ushadow-app.override.yml         # ushadow backend
```

**Shared network**: The Dockerized modules join an external Docker network called `memory-net`, enabling containers to reach services in other modules by container name. Internal service names stay module-scoped (chronicle's `mongo` is separate from ushadow's `mongo`).

To use an override manually (e.g., just chronicle + mycelia):

```bash
docker network create memory-net 2>/dev/null || true

docker compose -f chronicle/backends/advanced/docker-compose.yml \
  -f overrides/chronicle.override.yml up -d

docker compose -f mycelia/docker-compose.yml \
  -f overrides/mycelia.override.yml up -d
```

### Repository Structure

```
self-hosted-memory-assistants/
├── mycelia/              → mycelia-tech/mycelia
├── exocortex/            → amaslak0v/exocortex
├── ushadow/              → Ushadow-io/Ushadow
├── chronicle/            → chronicler-ai/chronicle
├── scripts/              → repo maintenance helpers
├── overrides/            → Docker Compose override files for combined mode
│   ├── chronicle.override.yml
│   ├── chronicle-speaker.override.yml
│   ├── chronicle-openmemory.override.yml
│   ├── chronicle-langfuse.override.yml
│   ├── mycelia.override.yml
│   ├── mycelia-gpu.override.yml
│   ├── ushadow-infra.override.yml
│   └── ushadow-app.override.yml
├── .env.ports            → Port assignment reference
├── start-all.sh          → Orchestration script
└── README.md
```

## Getting Started

### Unified setup from the meta-repo

If you want one entry point for all projects:

```bash
cp .setup.env.example .setup.env
./setup.sh
```

Optional:

```bash
./setup.sh --start
./setup.sh --dry-run
./setup.sh --projects mycelia,ushadow
```

See [UNIFIED_SETUP.md](UNIFIED_SETUP.md) for where databases live and where each project stores runtime secrets.

### Clone with submodules

```bash
git clone --recurse-submodules https://github.com/skywinder/self-hosted-memory-assistants.git
cd self-hosted-memory-assistants
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

## Working with Child Repositories

### Day-to-day development

Work inside any project as a standalone repo:

```bash
cd mycelia
git checkout dev
git pull origin dev
# make changes, commit, push as usual
git add .
git commit -m "your change"
git push
```

### Updating everything to the latest fast-forward state

Use the repo script instead of a blind recursive submodule update:

```bash
./scripts/update-subrepos.sh
```

What it does:

- Initializes declared top-level child repos if they are missing
- Updates `chronicle`, `exocortex`, `mycelia`, and `ushadow` with `git pull --ff-only`
- Initializes and updates the child repos declared inside `ushadow`
- Skips child repos that already have local changes instead of trying to pull through them
- Verifies that each target path is a real repo root before pulling, so an empty gitlink directory does not accidentally resolve to the parent repo
- Warns about gitlinks that exist in `ushadow` but are not declared in `ushadow/.gitmodules` and therefore cannot be initialized safely by recursive submodule commands

Preview what it would touch:

```bash
./scripts/update-subrepos.sh --dry-run
```

Only update the top-level repos tracked by this meta-repo:

```bash
./scripts/update-subrepos.sh --root-only
```

### Recording which versions go together

After updating child repos, review the changed gitlinks and commit the new pointers in the parent repo that owns them:

```bash
git status
git -C ushadow status
```

Typical follow-up:

```bash
git -C ushadow add chronicle mycelia openmemory vibe-kanban
git -C ushadow commit -m "bump nested child repos"

git add chronicle exocortex mycelia ushadow
git commit -m "bump child repos"
git push
```

If `git -C ushadow status` is clean, you only need the top-level `git add ...` and commit.

### Detached HEADs and nested repos

Fresh submodule checkouts often start detached. The updater script will attach a detached child repo to each repo's `origin/HEAD` before pulling.

`ushadow` also carries nested gitlinks. Not all of them are declared cleanly in `ushadow/.gitmodules`, so `git submodule update --remote --recursive` is not a reliable maintenance workflow here.

### Switching branches inside a child repo

To work on a specific branch by hand:

```bash
cd chronicle
git checkout dev
```

### Quick reference

| Task | Command |
|------|---------|
| Clone everything | `git clone --recurse-submodules <url>` |
| Init submodules after clone | `git submodule update --init --recursive` |
| Preview repo updates | `./scripts/update-subrepos.sh --dry-run` |
| Pull all latest safely | `./scripts/update-subrepos.sh` |
| Pull top-level only | `./scripts/update-subrepos.sh --root-only` |
| See submodule status | `git submodule status` |
| Work on a project | `cd <project> && git checkout <branch>` |
| Record version bump | `git add <project> && git commit` |
| Install Exocortex deps | `npm ci --prefix exocortex/control-panel` |
| Start all (combined mode) | `./start-all.sh up` |
| Stop all | `./start-all.sh down` |
| Check running containers | `./start-all.sh status` |

## License

Each project maintains its own license. See individual project directories.
