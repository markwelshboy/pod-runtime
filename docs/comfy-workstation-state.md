# Portable ComfyUI workstation state

## Goal

Make a disposable Vast/RunPod ComfyUI pod behave like a persistent local workstation.

A new pod should reconstruct the deterministic parts of the previous environment, carry forward the genuinely unique mutable state, and avoid dragging hundreds of gigabytes of reproducible model data through every snapshot.

The governing rule is:

> **Snapshot entropy; reconstruct deterministic state.**

This extends the existing `configure-pod` / `snapshot-pod` project-state machinery rather than replacing it. The current project snapshot manifest remains responsible for repository and snapshot restore state. ComfyUI workstation inventory is a second layer beneath `/workspace/.pod-state/` that records assets, provenance, references, activity, custom-node state, and output archival state.

## State classes

Every interesting path should converge on one of four storage decisions.

| Class | Examples | Local policy | Snapshot policy |
| --- | --- | --- | --- |
| Base | ComfyUI seed, Python, Torch, system packages | supplied by image | never |
| Reconstructable | HF/Civitai models, clean custom-node repos | materialize on demand | metadata only |
| Unique mutable | workflows, inputs, user config, selected/pinned outputs | keep | payload |
| Transient unknown | manually copied models, experimental files, dirty-node overlays | keep while active | payload until adopted or expired |

A fifth state, **archived**, applies mainly to outputs: the original payload is safely stored remotely, while a lightweight searchable/visual catalogue remains available.

## On-disk state

For a ComfyUI workstation named `comfy`, the proposed local metadata is:

```text
/workspace/.pod-state/comfy/
  manifest.json             # existing project snapshot state, when used by a template
  workstation.json          # reconciled current inventory / lock state
  events.jsonl              # append-only acquisition/use/adoption/archive events
  snapshot_parent           # existing snapshot lineage marker
  overlays/
    custom_nodes/
      <node-id>/
        working-tree.patch
        untracked.tar.zst
```

`workstation.json` is generated state. Human policy remains in repository configuration; exact runtime facts are recorded in the workstation lock state.

## Workstation manifest

Initial schema:

```json
{
  "schema_version": 1,
  "created_utc": "2026-09-12T20:00:00Z",
  "comfy_root": "/workspace/ComfyUI",
  "assets": [],
  "workflows": [],
  "custom_nodes": [],
  "outputs": {},
  "summary": {}
}
```

### Asset record

```json
{
  "path": "models/loras/example.safetensors",
  "size": 812345678,
  "mtime_ns": 0,
  "atime_ns": 0,
  "kind": "model",
  "state": "transient",
  "provenance": {
    "type": "unknown"
  },
  "references": {
    "workflows": ["user/default/workflows/foo.json"]
  },
  "activity": {
    "referenced": true,
    "last_reference_utc": null,
    "last_execution_utc": null
  }
}
```

When provenance is known, `state` becomes `reconstructable` and the payload no longer needs to be in the snapshot. Provenance types initially include `huggingface`, `civitai`, `git`, `owned`, and `unknown`.

## Acquisition journal

Download/install helpers should append successful actions to `events.jsonl` only after the payload is present and validated.

Example HF event:

```json
{"schema_version":1,"time":"2026-09-12T20:00:00Z","event":"asset_acquired","source":"huggingface","repo":"owner/repo","remote_path":"model.safetensors","destination":"/workspace/ComfyUI/models/diffusion_models/model.safetensors","revision":"..."}
```

Example Civitai event:

```json
{"schema_version":1,"time":"2026-09-12T20:00:00Z","event":"asset_acquired","source":"civitai","model_id":123,"version_id":456,"destination":"/workspace/ComfyUI/models/loras/foo.safetensors"}
```

The reconciler combines journal provenance with what actually exists on disk. Instrumentation is useful evidence, never the sole source of truth.

## Reconciliation and safety

Before a workstation snapshot:

1. scan known ComfyUI state locations;
2. load acquisition/adoption/archive events;
3. parse workflows and record asset filename references;
4. inspect `custom_nodes` repositories;
5. classify each payload as reconstructable, unique, transient, or archived;
6. identify untracked large files;
7. refresh activity evidence;
8. write `workstation.json`;
9. show actionable warnings;
10. snapshot only paths that still contain entropy.

Unknown data is preserved first. Garbage collection happens only after a verified reconstruction/archive path exists or the transient retention policy has clearly expired it.

## Usage evidence

Do not make destructive decisions from filesystem `atime` alone. It may be affected by `relatime`, `noatime`, mounts, and our own scans.

Evidence strength is:

1. workflow execution referencing the asset;
2. recent active/edited workflow reference;
3. any workflow reference;
4. trustworthy filesystem access time;
5. merely existing on disk.

Workflows are dependency-graph roots. A model referenced by an active workflow is considered live even if its filesystem access time is old.

The first implementation deliberately records workflow references without pretending they are executions. Execution telemetry can be added later from ComfyUI history / prompt events.

## Workflow references

The scanner recursively walks workflow JSON strings and indexes plausible model filenames. It then resolves those references against model files under `ComfyUI/models`.

A reference may be:

- resolved uniquely;
- ambiguous (same basename in multiple model directories);
- missing (workflow refers to a model not present locally).

All three are useful. Missing references later enable lazy materialization from recorded provenance.

Custom-node workflow dependencies should reuse the existing pack-aware workflow resolver and Manager metadata rather than inventing a second node-type mapping system.

## Custom-node lifecycle

The existing `custom_nodes_manifest.json` is the source of baseline node sets. Those sets describe intent: nodes that should be present regardless of immediate workflow references.

Runtime node states are:

- **baseline** — member of the selected/default node set;
- **transient-active** — not baseline, but referenced by recent workflows or otherwise used;
- **transient-cold** — known clean git repo, not currently needed;
- **promoted** — added deliberately to a persistent custom-node set;
- **retired** — checkout may disappear, but repo/ref metadata remains for historical reconstruction.

A clean custom-node checkout is reconstructable from remote + exact commit and normally contributes no payload to the workstation snapshot.

A dirty checkout contains entropy. Snapshot should preserve only:

- base remote and commit;
- `git diff --binary` patch;
- untracked files required to recreate the working tree.

Repeatedly used transient nodes should be surfaced as promotion candidates. Promotion means adding them to an owned custom-node manifest/set, after which every new workstation gets them by policy.

## Output lifecycle

Outputs are not ordinary snapshot payloads. They have a tiered lifecycle:

- **hot** — recent outputs carried automatically to the next pod;
- **pinned** — explicitly retained locally regardless of age;
- **warm/archive** — original stored remotely, catalogue retained, not restored automatically.

Recommended starting policy:

```yaml
outputs:
  archive_every_days: 7
  keep_local_days: 30
  archive_backend: huggingface
  verify_before_evict: true
```

This intentionally follows **archive early, evict late**. A weekly archive can be verified while the originals remain in the 30-day hot window.

### Archive bundle

A weekly archive should look like:

```text
2026/09/outputs-2026-09-08--2026-09-14.tar.zst
2026/09/outputs-2026-09-08--2026-09-14.manifest.json
2026/09/outputs-2026-09-08--2026-09-14.contact-sheet.jpg
2026/09/outputs-2026-09-08--2026-09-14.index.html
2026/09/thumbs/...
2026/09/previews/...
```

The **catalogue** (manifest, contact sheet, thumbnails, previews, HTML) is cheap to fetch and browse. The **payload** archive is fetched only when an original is required.

The archive backend must be abstract. HF is the first backend because it is already fast and available, but the manifest should not care whether the payload later lives on HF, S3/R2, rclone storage, or a NAS.

## Garbage collection

Transient payloads follow:

```text
discover -> preserve -> observe -> adopt or expire
```

A conservative default might require both age and multiple snapshots before automatic eligibility:

```yaml
gc:
  transient_unused_days: 14
  transient_min_snapshots: 2
  cold_days: 45
```

Workflow references can keep an asset active. An asset repeatedly consumed while still untracked should generate a normalization recommendation:

- record its HF/Civitai source;
- adopt it into an owned HF asset repo;
- deliberately mark it snapshot-owned;
- or keep it transient for now.

Deletion should remain a visible policy decision until the observation model has proved trustworthy.

## Restore strategy

Restore is dependency-driven:

1. restore unique workstation data (workflows, input, user config, hot/pinned output);
2. install baseline custom-node set;
3. inspect restored active workflows;
4. restore required transient custom-node repos at recorded commits;
5. materialize referenced models from HF/Civitai/owned sources;
6. apply dirty custom-node overlays;
7. validate unresolved references;
8. start ComfyUI.

Later, `configure-pod ... --lazy` can materialize only the current/recent workflow working set instead of every historically known model.

## CLI direction

The existing commands stay intact. The state layer grows incrementally:

```text
pod-state workstation scan [--root /workspace/ComfyUI]
pod-state workstation status
pod-state workstation record ...
pod-state workstation adopt PATH ...
pod-state workstation gc [--dry-run]
pod-state outputs archive [--dry-run]
pod-state outputs restore ...
```

`snapshot-pod` should eventually run the equivalent of `workstation scan` before archive creation and include the generated lock state automatically.

## Implementation phases

### Phase 1 — inventory and workflow references

- add a dependency-free ComfyUI workstation scanner;
- inventory model files, workflows, outputs, and custom-node git checkouts;
- map workflow string references to local model payloads;
- distinguish baseline custom nodes from transient checkouts;
- expose `scan` and human-readable `status` primitives;
- unit test using synthetic ComfyUI trees.

This phase is read-only except for writing generated state under `.pod-state`.

### Phase 2 — acquisition provenance and snapshot reconciliation

- append provenance events from `hff` after successful downloads;
- add Civitai accelerator event hook;
- reconcile events with disk inventory;
- show unknown/reconstructable bytes before `snapshot-pod`;
- automatically include workstation lock state in snapshots;
- exclude proven-reconstructable payloads from workstation snapshot plans.

### Phase 3 — custom-node overlays and promotion

- persist clean repo commit/ref records;
- capture dirty patches/untracked overlays;
- reuse workflow-to-pack resolver for custom-node references;
- add `promote` into named/default custom-node sets;
- restore baseline + active transient node sets.

### Phase 4 — output archive catalogue

- configurable hot/pinned windows;
- weekly archive bundles;
- JSON catalogue + thumbnails + contact sheet + static HTML index;
- HF backend first, storage backend abstraction underneath;
- verify archive before local eviction;
- selective restore.

### Phase 5 — execution-aware activity and lazy restore

- ingest ComfyUI execution/history evidence;
- track strongest last-use signal separately from `atime`;
- dependency-driven model/node materialization;
- conservative automated transient GC.

## Validation strategy

This work lives on `feature/comfy-workstation-state` until the state model has been exercised against real disposable pods.

Validation should specifically prove:

1. scans never modify model/workflow payloads;
2. workflow references prevent useful transient assets from being classified orphaned;
3. unknown files are preserved rather than silently discarded;
4. clean custom-node repos can be deleted and reconstructed exactly;
5. dirty custom-node repos round-trip through an overlay;
6. archived outputs are not evicted until remote verification succeeds;
7. old workflows remain capable of requesting cold models/nodes without carrying them on every pod.
