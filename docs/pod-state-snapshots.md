# Disposable pod project state

`configure-pod` and `snapshot-pod` make a provisioned pod disposable without teaching the generic provision step about each project.

The project template describes stable configuration: repository URLs/locations, repo-owned configure scripts, and data paths to preserve. Mutable source state such as branch and commit is recorded only in each snapshot manifest.

## Qwen3 captioning

Fresh environment:

```bash
configure-pod qwen3-captioning
```

Restore the newest saved environment:

```bash
configure-pod qwen3-captioning --snapshot latest
```

Restore a particular snapshot:

```bash
configure-pod qwen3-captioning --snapshot 20260901_120000__qwen3-captioning
```

Before terminating the pod:

```bash
snapshot-pod qwen3-captioning
```

An optional label can make a checkpoint easier to recognize:

```bash
snapshot-pod qwen3-captioning --name before-crop-fusion-change
```

Both commands also accept the explicit form used by older pod scripts:

```bash
configure-pod --template qwen3-captioning --snapshot latest
snapshot-pod --template qwen3-captioning
```

Use `--dry-run` on either command to inspect the plan without changing project state or creating a snapshot.

## Snapshot layout

Each template gets a dedicated HFF snapshot directory:

```text
pod-snapshots/<template-name>/
```

For `qwen3-captioning` this is:

```text
pod-snapshots/qwen3-captioning/
```

That makes `--snapshot latest` simply the newest HFF snapshot in that project-specific directory.

`HFF_REPO` / `HFF_REPO_TYPE` are honored when set. Otherwise the same `HF_MY_REPO_ID` / `HF_MY_REPO_TYPE` defaults used by the existing pod-runtime HFF helpers are used.

A small pod-state manifest is stored inside the snapshot at:

```text
/workspace/.pod-state/<template-name>/manifest.json
```

It records, per repository:

- branch (or detached state)
- exact commit SHA
- upstream
- ahead/behind counts
- dirty status and porcelain status lines
- repository URL/path

Branch is intentionally **not** stored in the template.

## Source-state safety

By default `snapshot-pod` refreshes `origin` and refuses to create a normal snapshot if a declared repository:

- has modified, staged, or untracked files;
- has no upstream branch; or
- contains commits ahead of its upstream.

This avoids a successful run-data snapshot being mistaken for a complete recovery point when the corresponding code is not recoverable from GitHub.

After committing/pushing, rerun `snapshot-pod`. `--force` exists for deliberate exceptions, but the command warns that source code may not be fully recoverable.

## Restore order

For a snapshot restore, `configure-pod` performs this sequence:

1. resolve the template;
2. resolve `latest` or the requested snapshot ID;
3. download/extract the HFF snapshot into a temporary staging directory;
4. read the saved pod-state manifest;
5. clone/fetch each declared repository;
6. restore the exact saved commit and branch;
7. hydrate saved `/workspace` data;
8. run the repo-owned configure scripts from that restored checkout.

For a fresh configure there is no snapshot/manifest: the repo is cloned at its remote default branch and the same configure scripts are run.

## Template

The first template is `snapshot-templates/qwen3-captioning.yaml`. Built-in templates use JSON-compatible YAML so they can be parsed by the Python standard library on minimal pods; conventional YAML is also accepted when PyYAML is installed.

```yaml
{
  "version": 1,
  "name": "qwen3-captioning",
  "workspace": "/workspace/qwen3",
  "repos": [
    {
      "name": "captioning",
      "url": "https://github.com/markwelshboy/qwen3-vl-captioning-validation.git",
      "path": "/workspace/qwen3/qwen3-vl-captioning-validation",
      "configure": {
        "scripts": [
          "./build_workspace.sh",
          "./build_sam3d_workspace.sh",
          "./build_vllm_workspace.sh"
        ]
      }
    }
  ],
  "snapshot": {
    "paths": [
      "/workspace/qwen3/qwen3-vl-captioning-validation/runs",
      "/workspace/qwen3/images"
    ]
  }
}
```

The build/configure scripts remain owned and versioned by the project repository. A restored snapshot therefore runs the scripts from the exact source checkout that the snapshot recorded.
