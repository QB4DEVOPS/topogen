<!--
File Chain (see DEVELOPER.md - this file!):
Doc Version: v1.5.0

- Called by: Developers (new contributors, AI assistants), maintainers
- Reads from: Codebase analysis, architecture decisions, team conventions
- Writes to: None (documentation only, but guides all development)
- Calls into: References README.md, TESTED.md, CONTRIBUTING.md, TODO.md, code files

Purpose: Developer-oriented guide to TopoGen codebase, file chains, validation, and workflows.
         Primary reference for understanding code structure, dependencies, and development process.

Blast Radius: None (documentation only, but critical for developer onboarding and AI navigation)
-->

# Developer notes



This file is a developer-oriented starting point for TopoGen.



## Quick start (skim)



- If you are new here, read:

  - `README.md` (user-facing behavior and examples)

  - `DEVELOPER.md` (this file)

- Core flow (where to look first):

  - CLI flags: `src/topogen/main.py`

  - Topology + rendering behavior: `src/topogen/render.py`

  - Device configs: `src/topogen/templates/*.jinja2`

- Validate changes:

  - Prefer offline first: generate `--offline-yaml out\<lab>.yaml` and search output with PowerShell `Select-String`.

  - Then (if needed) boot in CML and run basic show commands (see "How to validate changes").

## Architecture at a glance

High-level execution flow showing the authoritative engine and delivery paths.

```mermaid
graph TD
    classDef input fill:#5c7aff,stroke:#333,color:#fff,stroke-width:2px;
    classDef engine fill:#3b59ff,stroke:#333,color:#fff,stroke-width:2px;
    classDef logic fill:#444,stroke:#333,color:#fff,stroke-width:1px;
    classDef output fill:#2ecc71,stroke:#333,color:#fff,stroke-width:2px;

    subgraph Entry ["User Interface"]
        CLI[TopoGen CLI<br/>main.py]
    end

    subgraph Config ["Parsing"]
        MAIN[config.py<br/>Config.load]
    end

    subgraph Core ["Engine"]
        RENDER[render.py<br/>Authoritative Engine]
    end

    subgraph Tasks ["Core Responsibilities"]
        TOP[Topology Logic<br/>models.py]
        TMP[Render Configs<br/>templates/*.jinja2]
        PKI[PKI/CA Handling<br/>csr-pki-ca.jinja2]
    end

    subgraph Destination ["Delivery"]
        YAML[Offline CML YAML<br/>--offline-yaml]
        LIVE[Live CML Controller<br/>virl2_client API]
    end

    CLI --> MAIN
    MAIN --> RENDER
    RENDER --> TOP
    RENDER --> TMP
    RENDER --> PKI
    TOP --> YAML
    TOP --> LIVE
    TMP --> YAML
    TMP --> LIVE
    PKI --> YAML
    PKI --> LIVE

    class CLI input;
    class MAIN engine;
    class RENDER engine;
    class TOP,TMP,PKI logic;
    class YAML,LIVE output;
```

## Tested platforms

For detailed version information (Python, CML servers, node images, dependencies), see [TESTED.md](TESTED.md).

**TL;DR**: Python 3.12.0, CML 2.6.1/2.7.0, CSR1000v 17.3, IOSv 15.9, Windows 11.

## 5-minute environment validation



Before making any changes, verify your environment is working:



### 1. Check package version matches repo



```powershell

topogen -v

```



Expected: version should match `pyproject.toml` or show "Unreleased" if installed editable with `-e .`



If the version is stale, reinstall editable:



```powershell

python -m pip install -e .

```



### 2. Generate a small offline lab



```powershell

topogen -T iosv-eigrp --device-template iosv -m flat --offline-yaml out\env-test.yaml --overwrite 4

```



Expected output includes:

- Progress through "creating" nodes and links

- "Offline YAML written to out\env-test.yaml"



### 3. Validate the generated YAML



```powershell

Select-String -Path out\env-test.yaml -Pattern "node_definition: iosv"

```



Expected: 4+ matches (1 per router + DNS host)



```powershell

Select-String -Path out\env-test.yaml -Pattern "router eigrp 100"

```



Expected: 4 matches (1 per router config)



### 4. Verify templates are loadable



```powershell

topogen --list-templates

```



Expected: list of available templates including `iosv`, `iosv-eigrp`, `csr-eigrp`, `iosv-dmvpn`, etc.



### What this proves



- Python environment is working

- TopoGen package is installed and current

- Templates are accessible

- Offline YAML generation works

- Output directory (`out\`) is writable



If any step fails, troubleshoot before proceeding:

- Virtual environment activated?

- Package installed editable (`pip install -e .`)?

- Working directory is repo root?

## What TopoGen is



TopoGen is a Python CLI tool that generates CML labs:



- **Online**: creates labs/nodes/links on a CML controller via the PCL (`virl2-client`).

- **Offline**: writes a CML YAML lab file locally with `--offline-yaml`.



It also renders per-node startup-configs using **Jinja2 templates**.



Terminology:



- `-T` / `--template`: which config template to render (`src/topogen/templates/*.jinja2`)

- `--device-template`: which CML node definition to use (e.g., `iosv`, `csr1000v`)



Pitfall:



- In general, keep the config template (`-T`) aligned with the device template (`--device-template`). For example, using an IOSv config template on a CSR1000v node definition can result in wrong interface names or unsupported config at boot.



## Authoritative sources of truth



- `src/topogen/render.py`: topology semantics + rendering behavior (authoritative engine)

- `src/topogen/templates/*.jinja2`: emitted device configuration (what nodes boot with)

- `README.md`: user-facing CLI contract and examples

- `CHANGES.md`: what changed between released versions

- `TODO.md`: in-progress ideas/roadmap (not guaranteed implemented)



Maintenance note:

- Some offline YAML generation features (notably `--mgmt-bridge` external_connector emission and related OOB switch/link wiring) currently appear as repeated blocks across multiple offline renderers in `src/topogen/render.py`. This is intentional for now, but it increases maintenance cost (a future edit could fix one mode and miss another). Prefer refactoring into a shared helper when touching this area again.



## Runtime dependencies (from `pyproject.toml`)



Required:



- `jinja2` (template rendering)

- `virl2-client` (CML controller API client for online mode)

- `pyserde[toml]` (read/write `config.toml`)

- `networkx` (topology logic in some modes)

- `enlighten` (progress bars)



Optional:



- `gooey` (GUI entrypoint)



## Repository layout (what matters)



Required to run:



- `pyproject.toml`

- `src/topogen/`

  - `__init__.py` (package entrypoint exposure)

  - `main.py` (CLI parsing, dispatch)

  - `render.py` (authoritative topology + rendering engine)

  - `config.py` (config model + load/save)

  - `models.py` (dataclasses + `TopogenError`)

  - `templates/` (all `*.jinja2` templates)



Nice to have:



- `README.md` (user docs)

- `CHANGES.md` (release notes)

- `TODO.md` (roadmap)

- `.github/workflows/` (CI)

- `.images/` (demo assets)

- `CONTRIBUTING.md` (contributor workflow)



## Entry points



Defined in `pyproject.toml`:



- `topogen = topogen:main`

- `topogen-gui = topogen.gui:main`



These resolve through `src/topogen/__init__.py` and then into the real logic:



- CLI: `src/topogen/main.py:main()`

- GUI: `src/topogen/gui.py:main()` (wraps the same CLI parsing and then calls `topogen.main.main()`)



## High-level dependency chain (call graph)



When you run `topogen ...`:



1. `src/topogen/main.py`

   - Parses args (argparse)

   - Loads config via `src/topogen/config.py` (`Config.load()`)

   - Selects the topology mode and template

   - Calls into `src/topogen/render.py` (`Renderer`) for online or offline generation



2. `src/topogen/render.py`

   - Builds nodes/links + addressing

   - Loads templates from `src/topogen/templates/` (package resources)

   - Renders per-node configs using Jinja2

   - Either:

     - writes offline YAML, or

     - uses `virl2_client.ClientLibrary` to create/update the lab on a controller



3. `src/topogen/templates/*.jinja2`

   - Produce IOS/IOS-XE configs based on the passed Jinja context (`config`, `node`, and feature flags)



## AI onboarding prompt (copy/paste)



Paste this into a fresh AI session to get it oriented quickly:



```text

You are working in the TopoGen repo (Python 3.12+). Start by reading DEVELOPER.md.



Goal: implement a small feature or bugfix without breaking existing modes.



Key flow:

- CLI entrypoint: src/topogen/main.py

- Authoritative topology + rendering: src/topogen/render.py

- Device configs: src/topogen/templates/*.jinja2



When adding a feature:

1) add/modify CLI flags in main.py

2) pass the flag into render.py logic and into the Jinja context

3) implement emitted config lines in the relevant template(s)

4) update README.md + CHANGES.md

5) validate with an offline YAML lab and (if applicable) an online controller run



Use the "File pointers" section in DEVELOPER.md to understand what each file reads/writes/calls.
Every file and every template has a File Chain header at the top (Doc Version, Called by, Reads from, Writes to, Calls into); this includes docs and other required files—read it for blast radius and dependencies (AI-first onboarding).

```



## AI guardrails (default boundaries)

**When to act (mandatory):**

- Do not do anything unless the user has **expressly and explicitly** told you to do it. Ask the user for approval before running commands or editing files.
- **Questions or statements are not instructions.** If the user asks a question (e.g. "why is X?") or makes a statement (e.g. "X should be Y"), only answer or explain. Do not treat that as a request to change code, run a command, or edit files — unless the user has explicitly updated their instructions (e.g. "then change it" or "add that to the doc").
- End every response with exactly one of: **Done** | **Stopped** | **Blocked** | **I am confused** | **What options do you want me to do: 1, 2, or 3?** | **Task completed**.

Unless a task explicitly requires otherwise:



- Prefer editing:

  - `src/topogen/main.py` (CLI flags + wiring)

  - `src/topogen/render.py` (behavior + Jinja context)

  - `src/topogen/templates/*.jinja2` (emitted device config)

  - Docs: `README.md`, `CHANGES.md`, `DEVELOPER.md`



- Avoid editing (high blast radius) unless asked:

  - `pyproject.toml` (dependencies, entrypoints, packaging metadata)

  - `src/topogen/__init__.py` (entrypoint exposure)

  - `.github/workflows/*` (CI behavior)

  - `.gitignore` (what artifacts get committed)



- Never commit generated artifacts:

  - `out\` (gitignored offline YAML outputs)



## Common tasks -> file chain (LLM-friendly)



- **Add a new CLI flag**

  - `src/topogen/main.py` (argparse)

  - `src/topogen/render.py` (consume the flag + pass into Jinja context)

  - `src/topogen/templates/*.jinja2` (emit config)

  - Docs: `README.md`, `CHANGES.md`



- **Change how addressing/topology is computed**

  - `src/topogen/render.py`

  - `src/topogen/models.py` (only if new per-node/per-link fields are needed)

  - Docs: `README.md` (if user-visible)



- **Change device config text (without changing topology logic)**

  - `src/topogen/templates/*.jinja2`

  - `src/topogen/render.py` (only if you need to add context variables)



- **Change online (controller) behavior**

  - `src/topogen/render.py` (calls `virl2_client`)

  - Docs: `README.md` (env vars / flags)



- **Change config.toml defaults/parsing**

  - `src/topogen/config.py`

  - `src/topogen/main.py` (wire flags like `--config`, `--write`)



## Worked example: `--eigrp-stub` flag



Reference implementation:



- Commit: `bfe0498` (feat(dmvpn): add --eigrp-stub for flat-pair evens)



Goal:



- Add a CLI flag `--eigrp-stub` that enables `eigrp stub connected summary` in the generated router configs (scoped by topology rules).



Typical change pattern (what got edited):



- `src/topogen/main.py`

  - Add the CLI flag and plumb it into the rendering call.

- `src/topogen/render.py`

  - Decide which nodes should be treated as “stub” based on the selected mode/underlay.

  - Pass the stub decision into the Jinja rendering context.

- `src/topogen/templates/*.jinja2`

  - Emit `eigrp stub connected summary` when the context indicates stub should be enabled.

- Docs

  - Update `README.md` and `CHANGES.md` to reflect the new flag and its semantics.



Validation pattern:



- Generate an offline YAML lab and search for the emitted config line:



```powershell

topogen --cml-version 0.3.0 -m dmvpn --dmvpn-underlay flat-pair -T iosv-dmvpn --device-template iosv --eigrp-stub --offline-yaml out\test.yaml --overwrite 20

Select-String -Path out\test.yaml -Pattern "eigrp stub connected summary"

```



## File pointers (called-by / reads-from / writes-to / calls-into)



The intent of this section is to reduce guesswork.



If this file and the code disagree, treat the code as authoritative and update `DEVELOPER.md` in the same PR.



- For an **AI**, these pointers help answer: "Where do I edit, and what else must I touch?"

- For a **human**, these pointers help answer: "What are the side effects and blast radius of a change?"



### Understanding the File Chain Terms



Each file in this codebase includes file chain documentation (in code comments or docstrings) using four key terms. This makes every file self-documenting for both humans and AI assistants. Here's what each term means:



- **Called by**: Which files, functions, or systems invoke this code

  - Answers: "Who triggers this?"

  - Example: `src/topogen/render.py` is called by `src/topogen/main.py`

  - Impact: If you change this file's interface (function signature, exports), you must update all callers



- **Reads from**: What input data this code consumes

  - Answers: "What does this depend on?"

  - Examples: Config files, environment variables, Jinja context variables, API responses

  - Impact: If you change what this file expects, you must ensure those inputs are provided correctly



- **Writes to**: What output or side effects this code produces

  - Answers: "What does this change or create?"

  - Examples: Files written to disk, API calls that modify remote state, stdout/logging

  - Impact: If you change what this file outputs, you must ensure downstream consumers can handle it



- **Calls into**: What downstream dependencies this code triggers

  - Answers: "What does this invoke?"

  - Examples: Other Python modules, Jinja templates, external libraries, API clients

  - Impact: If you change what this file calls, you must ensure those dependencies exist and work correctly



**Why this matters**:

- **Blast radius**: Quickly understand what breaks if you modify a file

- **Dependencies**: Trace the full chain from CLI input to final output

- **Self-documentation**: Read any single file and immediately understand its role

- **AI-friendly**: Enables assistants to navigate the codebase without guessing



### Document Versioning (MANDATORY)

**IMPORTANT**: Every documentation file must include a `Doc Version` in its file chain header.

**Format**: `Doc Version: v{major}.{minor}.{patch}` (semantic versioning)

**Versioning Rules** (based on conventional commits):
- **MAJOR** (v1.0.0 → v2.0.0): Breaking changes to documentation structure or format
  - Triggered by: Commits with `BREAKING CHANGE:` in footer, or `!` after type (e.g., `docs!:`)
  - Example: Restructuring file chain format, removing sections, changing header structure

- **MINOR** (v1.0.0 → v1.1.0): New content, features, or sections
  - Triggered by: `feat(scope):` commits
  - Example: Adding new sections, new features documentation, new examples

- **PATCH** (v1.0.0 → v1.0.1): Corrections, clarifications, or non-breaking updates
  - Triggered by: `fix(scope):`, `docs(scope):`, `chore(scope):` commits
  - Example: Typo fixes, clarifications, reformatting, minor updates

**Commit Message Examples**:
```bash
# PATCH bump (v1.0.0 → v1.0.1)
docs(developer): fix typo in versioning section
docs(readme): clarify installation steps
chore(tested): update Python version to 3.12.1

# MINOR bump (v1.0.0 → v1.1.0)
feat(developer): add PKI architecture section
feat(tested): add new CML 2.8.0 validation results

# MAJOR bump (v1.0.0 → v2.0.0)
docs(developer)!: restructure file chain header format

BREAKING CHANGE: File chain format now requires blast radius field
```

**File Examples**:

Markdown files:
```markdown
<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.0

- Called by: ...
-->
```

Python/TOML files:
```python
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
#
# - Called by: ...
```

Jinja2 templates (full format required for blast radius and AI-first onboarding):
```jinja2
{# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
#
# - Called by: ...
# - Reads from: ...
# - Writes to: ...
# - Calls into: ...
#}
```

**Workflow**:
1. Make your documentation changes
2. Bump the version number (minor or major)
3. Commit with message like `docs(readme): add usage examples (v1.0 → v1.1)`

**Why mandatory**:
- AI can track document evolution
- Reviewers know if changes are significant
- Version conflicts become visible
- Documentation gets same rigor as code



### `src/topogen/__init__.py`



- **Called by**

  - Console scripts via `pyproject.toml` entrypoints (`topogen = topogen:main`)

- **Reads from**

  - Package metadata via `importlib.metadata.metadata("topogen")`

- **Writes to**

  - None

- **Calls into**

  - `src/topogen/main.py` (exports `main`)

  - `src/topogen/render.py` (exports `Renderer`)

  - `src/topogen/config.py` (exports `Config`)



### `src/topogen/main.py`



- **Called by**

  - `src/topogen/__init__.py` (entrypoint export)

  - `src/topogen/gui.py` (GUI wrapper)

- **Reads from**

  - `config.toml` (or `--config`) via `Config.load()`

  - Environment variables (direct): `LOG_LEVEL`

- **Writes to**

  - stdout/stderr (logging)

  - Delegates offline YAML / online controller changes to `render.py`

- **Calls into**

  - `src/topogen/config.py` (`Config`)

  - `src/topogen/render.py` (`Renderer`, `get_templates()`)

  - `src/topogen/models.py` (`TopogenError`)



### `src/topogen/render.py`



- **Called by**

  - `src/topogen/main.py`

- **Reads from**

  - Packaged templates in `src/topogen/templates/` (via `topogen.templates` package resources)

  - `Config` values (IP pools, credentials, domain)

  - Online controller auth (indirectly via `virl2-client` / environment): `VIRL2_URL`, `VIRL2_USER`, `VIRL2_PASS`

- **Writes to**

  - Offline YAML file (`--offline-yaml`)

  - Online CML controller state (labs/nodes/links/configs) via `virl2_client.ClientLibrary`

- **Calls into**

  - `jinja2` (render templates)

  - `virl2_client` (online API)

  - `src/topogen/dnshost.py` (`dnshostconfig()`)

  - `src/topogen/lxcfrr.py` (`lxcfrr_bootconfig()`)

  - `src/topogen/models.py` (TopogenNode/Interface models)



### Templates (`src/topogen/templates/*.jinja2`)

Each Jinja2 template includes a **File Chain header** in a comment at the top of the file: `File Chain`, `Doc Version`, `Called by`, `Reads from`, `Writes to`, `Calls into`. This is the single source of truth for blast radius and **AI-first onboarding**—read the header to know what the template depends on and what it emits. The same four-term format is used in Python/Markdown; see "Understanding the File Chain Terms" and the examples above.



### `src/topogen/templates/*.jinja2`



- **Called by**

  - `src/topogen/render.py` (Jinja render step)

- **Reads from**

  - Jinja context (commonly `config`, `node`, plus feature flags)

- **Writes to**

  - Startup-config text embedded into offline YAML, or pushed to the controller (online)

- **Calls into**

  - None (template-only)



### `src/topogen/config.py`



- **Called by**

  - `src/topogen/main.py` (loads config)

  - `src/topogen/render.py` (uses config values)

  - `src/topogen/dnshost.py` (uses config values)

- **Reads from**

  - `config.toml` (or `--config` path)

- **Writes to**

  - `config.toml` when `--write` / `Config.save()` is used

- **Calls into**

  - `serde.toml` (`from_toml`, `to_toml`)



### `src/topogen/models.py`



- **Called by**

  - `src/topogen/main.py` (`TopogenError`)

  - `src/topogen/render.py` (TopogenNode/Interface/CoordsGenerator)

  - `src/topogen/dnshost.py` (DNShost/TopogenNode)

- **Reads from**

  - None

- **Writes to**

  - None

- **Calls into**

  - None (pure dataclasses/types)



### `src/topogen/dnshost.py`



- **Called by**

  - `src/topogen/render.py`

- **Reads from**

  - Jinja context data (`Config`, `TopogenNode`, list of `DNShost` entries)

- **Writes to**

  - Returns a boot script string (DNS host config)

- **Calls into**

  - `jinja2` (renders the inline template)



### `src/topogen/gui.py`



- **Called by**

  - Console script `topogen-gui` (`pyproject.toml`)

- **Reads from**

  - CLI args via `sys.argv` (Gooey populates argv)

  - Optional dependency: `gooey`

- **Writes to**

  - stdout/stderr (errors when Gooey is not installed)

- **Calls into**

  - `src/topogen/main.py` (`create_argparser()`, `main()`)



## Offline vs online



- **Offline** (`--offline-yaml out\lab.yaml`):

  - No controller needed.

  - Produces a YAML you import into CML.

  - `out\` is gitignored by default; in some environments tools/assistants may not be able to read generated artifacts, so validate via terminal search (e.g., PowerShell `Select-String`) rather than asking a tool to open the file.



- **Online** (no `--offline-yaml`):

  - Requires controller env vars (typical):

    - `VIRL2_URL`

    - `VIRL2_USER`

    - `VIRL2_PASS`

  - Uses `--insecure` if your controller TLS cert is not trusted.



### Progress bars (`--progress`)



- Progress bars are **opt-in** (they only show when `--progress` is provided).

- Progress bars are supported for both:

  - Offline YAML generation (local CPU work)

  - Online controller lab creation (CML API calls + node/link creation)

- Offline generation can complete very quickly even for large node counts (it does not boot routers).



## Gooey (GUI) notes



TopoGen has an optional GUI wrapper that reuses the CLI.



- Install:

  - `pip install -e ".[gui]"`

- Run:

  - `topogen-gui`



How it works:



- `src/topogen/gui.py` imports Gooey late (so normal CLI usage does not require Gooey).

- Gooey uses the same argparse definition by calling `topogen.main.create_argparser(parser_class=GooeyParser)`.

- The GUI then calls the normal CLI `topogen.main.main()`.



Common gotchas:



- If you installed TopoGen non-editable, reinstall after local changes:

  - `python -m pip install .`

- If you installed editable, code changes are picked up automatically:

  - `python -m pip install -e .`

  - or for GUI: `python -m pip install -e ".[gui]"`

- If online mode fails with no output, rerun with `-l DEBUG`.



## Where to implement features



Rule of thumb:



- **New CLI flag**: `src/topogen/main.py` (argparse)

- **Topology behavior / when to apply config**: `src/topogen/render.py`

- **Config lines emitted**: `src/topogen/templates/*.jinja2`

- **New per-node data fields**: `src/topogen/models.py`

- **Config.toml default / parsing**: `src/topogen/config.py`



## How to validate changes



Offline (recommended first pass):



- Generate an offline YAML under `out\` (gitignored).

- Validate by searching the generated YAML/config text (PowerShell examples):

  - `Select-String -Path out\*.yaml -Pattern "eigrp stub connected summary"`

  - `Select-String -Path out\*.yaml -Pattern "router eigrp"`

  - `Select-String -Path out\*.yaml -Pattern "tunnel mode gre multipoint"`



Online (basic smoke checks once routers boot):



- Routing:

  - `show ip route`

  - `show ip eigrp neighbors` (if using EIGRP)

- DMVPN (if applicable):

  - `show dmvpn`

  - `show ip nhrp`

- Config presence:

  - `show run | include eigrp stub`



## Git workflow for this repo



- Branch naming:

  - `feat/<short-name>` for features

  - `fix/<short-name>` for bugfixes

  - `docs/<short-name>` for documentation-only changes

- Workflow:

  - Keep changes incremental (one feature per branch/PR).

  - Prefer squash-merge to keep history clean.

  - After merge: sync `main` locally and delete the feature branch.

- Interaction preference:

  - AIs/assistants can propose exact commands; you run them and share output.



## Feature closeout checklist



See the README checklist and follow it for any change that affects behavior. When updating **CHANGES.md** (Unreleased), list each modified file and its new Doc Version (rev) so reviewers can see what was touched and to what rev. Example: `Files: src/topogen/render.py (rev v1.0.0), README.md (rev v1.2.1)`.



- [Feature closeout checklist](README.md#feature-closeout-checklist-required)

