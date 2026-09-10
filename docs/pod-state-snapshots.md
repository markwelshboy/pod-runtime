# Disposable pod project state

`configure-pod`, `snapshot-pod`, and `configure-snapshot` make a provisioned pod disposable without teaching the generic provision step about each project.

The project template describes stable configuration: repository URLs/locations, repo-owned configure scripts, data paths to preserve, and optional snapshot retention. Mutable source state such as branch and commit is recorded only in each snapshot's pod-state manifest. Human checkpoint notes are stored in the HFF snapshot manifest and can be edited later without rebuilding the archive.

## Qwen3 captioning

### Fresh environment

A bare configure remains intentionally snapshot-free:

```bash
configure-pod qwen3-captioning
```

It configures the project from the template and remote default branch. Existing snapshots are not restored or consulted.

### Restore a snapshot

Browse the available snapshots interactively, including their human-readable name, tags, pin state, reason, and next action:

```bash
configure-pod qwen3-captioning --snapshot
```

Restore the newest saved environment directly:

```bash
configure-pod qwen3-captioning --snapshot latest
```

Restore a particular snapshot:

```bash
configure-pod qwen3-captioning --snapshot 20260901_120000__qwen3-captioning
```

For direct restores, the selected snapshot's journal is displayed before rehydration. The explicit `latest`/ID forms remain non-interactive so they are suitable for scripts.

`--prune-snapshots` can apply the template retention policy after a successful configure. It never prunes before rehydration:

```bash
configure-pod qwen3-captioning --snapshot --prune-snapshots
```

### Create a snapshot

The fast path remains fast:

```bash
snapshot-pod qwen3-captioning
```

A snapshot does not require human notes. They can be supplied inline when useful:

```bash
snapshot-pod qwen3-captioning \
  --name "Pose refiner baseline" \
  --why "SAM3D pose/framing integration is stable" \
  --next "Run blind-set comparison for laterality errors" \
  --tag pose-refiner \
  --tag qwen \
  --pin
```

`--note` and `--description` are aliases for `--why`. `--tag` is repeatable. `--pin` exempts a snapshot from retention pruning.

By default the Qwen3 template applies retention only **after** the new snapshot has been created, uploaded, verified, and had its journal metadata recorded. Use `--no-prune` to skip that cleanup for one snapshot, or `--prune` to request it for a template whose automatic pruning is disabled.

The source-safety rules are unchanged: `snapshot-pod` refuses dirty, untracked, or unpushed source state unless `--force` is supplied.

### Add or change notes later

`configure-snapshot` edits only the HFF snapshot manifest. It does not touch the tar archive.

Choose a snapshot interactively and edit its journal:

```bash
configure-snapshot qwen3-captioning
```

Patch the newest snapshot without changing unspecified fields:

```bash
configure-snapshot qwen3-captioning latest \
  --name "Good pose-refiner checkpoint" \
  --next "Test sentence replacement" \
  --tag baseline \
  --pin
```

Other useful patch operations are:

```bash
configure-snapshot qwen3-captioning latest --unpin
configure-snapshot qwen3-captioning latest --remove-tag baseline
configure-snapshot qwen3-captioning latest --clear-tags
configure-snapshot qwen3-captioning latest --show
```

When editing interactively, Enter preserves the current value and `-` clears a text field or the tag list.

## Snapshot journal

The HFF `.manifest.json` gains an optional `journal` object. Old snapshots without it remain valid and can be annotated after the fact.

```json
{
  "journal": {
    "schema_version": 1,
    "name": "Pose refiner baseline",
    "note": "SAM3D pose/framing integration is stable",
    "next": "Run blind-set comparison for laterality errors",
    "tags": ["pose-refiner", "qwen"],
    "pinned": true,
    "parent_snapshot": "20260909_221236__qwen3-captioning",
    "updated_utc": "2026-09-10T16:00:00Z"
  }
}
```

`parent_snapshot` is maintained automatically. A snapshot restored with `configure-pod --snapshot ...` becomes the parent of the next snapshot. After a successful snapshot, that new checkpoint becomes the parent for the following snapshot. A fresh `configure-pod` clears the lineage marker.

## Inspect and manage history

```bash
snapshot-pod list qwen3-captioning
snapshot-pod list qwen3-captioning --tag pose-refiner
snapshot-pod show qwen3-captioning latest
snapshot-pod prune qwen3-captioning --dry-run
snapshot-pod prune qwen3-captioning
snapshot-pod delete qwen3-captioning SNAPSHOT_ID
```

`delete` refuses a pinned snapshot unless it is first unpinned or `--force` is deliberately supplied. Automated retention also never deletes pinned snapshots, unreadable manifests, or snapshots whose timestamp cannot be established.

## Retention

The Qwen3 template currently uses:

```yaml
"retention": {
  "recent": 5,
  "daily": 7,
  "weekly": 4,
  "grace_hours": 48,
  "auto_prune_after_snapshot": true
}
```

Retention keeps the newest five checkpoints, enough checkpoints to represent seven distinct recent days, enough to represent four distinct recent ISO weeks, every pinned checkpoint, and every checkpoint within the 48-hour grace period. Overlapping generations are not duplicated. Among otherwise equivalent daily/weekly checkpoints, the newest representative is retained.

The grace period is particularly important for quick snapshots: a newly-created unannotated checkpoint cannot be automatically discarded before there has been time to go back and pin or describe it.

Pruning is intentionally ordered after creation/verification. The system never destroys an older recovery point in preparation for making a new one.

## Snapshot layout

Each template gets a dedicated HFF snapshot directory beneath the existing snapshot root:

```text
snapshot/pods/<template-name>/
```

For `qwen3-captioning` this is:

```text
snapshot/pods/qwen3-captioning/
```

If `HFF_SNAPSHOT_DIR` is exported, that value replaces the leading `snapshot` component. `HFF_REPO` / `HFF_REPO_TYPE` are honored when set; otherwise the existing `HF_MY_REPO_ID` / `HF_MY_REPO_TYPE` defaults are used.

A small machine-readable pod-state manifest is stored *inside* each snapshot at:

```text
/workspace/.pod-state/<template-name>/manifest.json
```

It records repository branch/detached state, exact commit SHA, upstream, ahead/behind counts, dirty status, porcelain status lines, and repository URL/path. Branch is intentionally **not** stored in the template.

The human journal described above lives in the HFF snapshot manifest beside the tar so it can be listed and edited without downloading the archive.

## Restore order

For a snapshot restore, `configure-pod` performs this sequence:

1. resolve the template and requested snapshot;
2. show the selected snapshot journal;
3. download/extract the HFF snapshot into a temporary staging directory;
4. read the saved pod-state manifest;
5. clone/fetch each declared repository;
6. restore the exact saved commit and branch;
7. hydrate saved `/workspace` data;
8. run the repo-owned configure scripts from that restored checkout;
9. record the selected checkpoint as the local lineage parent.

For a fresh configure there is no snapshot/manifest: the repo is cloned at its remote default branch and the same configure scripts are run. The local lineage parent is cleared.

Both configure and snapshot creation still support the explicit template form used by older pod scripts:

```bash
configure-pod --template qwen3-captioning --snapshot latest
snapshot-pod --template qwen3-captioning
```

Use `--dry-run` on configure or snapshot creation to inspect the underlying project-state plan without changing project state or creating a snapshot.
