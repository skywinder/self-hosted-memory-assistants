# Self-Hosted Memory Assistants

A meta-repository that ties together three self-hosted AI memory projects via git submodules. Each project captures, processes, and retrieves personal data — audio, conversations, memories — and they can be orchestrated together through ushadow.

## Projects

### [Mycelia](https://github.com/mycelia-tech/mycelia)

Self-hosted AI memory and timeline system. Captures personal data through voice memos, screenshots, and text, then organizes and retrieves it conversationally. Ask "What did I say about X last May?" and get personalized responses in your own words.

- **Stack:** Deno backend, React/Vite frontend, Python diarizator, MongoDB, Redis
- **Features:** D3.js interactive timeline, AI chat with memory access, audio transcription (Whisper), speaker diarization, object extraction (people, events, promises), full-text search, MCP server

### [Chronicle](https://github.com/chronicler-ai/chronicle)

AI-powered personal memory system for wearable devices. Captures continuous audio streams from OMI devices via WebSocket, transcribes speech, extracts memories using LLMs, and provides a searchable dashboard.

- **Stack:** FastAPI (Python), React dashboard, React Native mobile app, MongoDB, Qdrant
- **Features:** Real-time audio capture (Wyoming protocol), Deepgram/Parakeet transcription, memory extraction, semantic vector search, speaker recognition, job tracking pipeline

### [ushadow](https://github.com/Ushadow-io/Ushadow)

AI orchestration platform and unified dashboard. Acts as the central hub that integrates Chronicle, MCP services, Agent Zero, n8n workflows, and other services under one roof.

- **Stack:** FastAPI (Python), React frontend, MongoDB, Redis, Qdrant, Keycloak
- **Features:** Multi-service orchestration, Chronicle integration proxy, interactive CLI (`ush`), setup wizard, multi-environment isolation via git worktrees, Kubernetes-ready

## Getting Started

### Clone with submodules

```bash
git clone --recurse-submodules https://github.com/skywinder/self-hosted-memory-assistants.git
cd self-hosted-memory-assistants
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

### Repository structure

```
self-hosted-memory-assistants/
├── mycelia/          → mycelia-tech/mycelia
├── ushadow/          → Ushadow-io/Ushadow
├── chronicle/        → chronicler-ai/chronicle
└── README.md
```

Each subfolder is a full git repository. You work inside them as normal.

## Working with Submodules

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

### Recording which versions go together

After updating a submodule, go back to the meta-repo and commit the new pointer:

```bash
cd ..  # back to self-hosted-memory-assistants/
git add mycelia
git commit -m "bump mycelia to latest"
git push
```

This records that "mycelia is now at commit X" in the meta-repo.

### Updating all submodules to latest

```bash
git submodule update --remote
git add .
git commit -m "bump all submodules to latest"
git push
```

### Pulling updates (including submodules)

```bash
git pull
git submodule update --init --recursive
```

Or in one command:

```bash
git pull --recurse-submodules
```

### Switching branches inside a submodule

Submodules check out in "detached HEAD" by default. To work on a branch:

```bash
cd chronicle
git checkout main
```

### Quick reference

| Task | Command |
|------|---------|
| Clone everything | `git clone --recurse-submodules <url>` |
| Init submodules after clone | `git submodule update --init --recursive` |
| Pull all latest | `git submodule update --remote` |
| See submodule status | `git submodule status` |
| Work on a project | `cd <project> && git checkout <branch>` |
| Record version bump | `git add <project> && git commit` |

## License

Each project maintains its own license. See individual project directories.
