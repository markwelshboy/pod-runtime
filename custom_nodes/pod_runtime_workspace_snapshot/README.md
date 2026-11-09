# Pod Runtime Workspace Snapshots (ComfyUI)

A ComfyUI frontend/backend extension that captures **every open workflow tab,
including unsaved graph edits**. It can also launch the existing pod-runtime
snapshot-pod uploader. It does not change ComfyUI Tab Manager or add graph nodes.

## Installation

The pod-runtime/start.sh bootstrap automatically symlinks this custom node into
the persistent ComfyUI custom-node directory unless
INSTALL_WORKSPACE_SNAPSHOT_NODE=false.

For a pod that is already running, update pod-runtime safely and install the
symlink once:

    ln -s /workspace/pod-runtime/custom_nodes/pod_runtime_workspace_snapshot \
      /workspace/ComfyUI/custom_nodes/pod_runtime_workspace_snapshot

Check that the target does not already exist before running this command.
Restart ComfyUI and hard-refresh the browser.

The extension requires snapshot-pod with --paths / --group on PATH or at
/workspace/pod-runtime/snapshot-pod. It has no additional Python dependencies
beyond ComfyUI's aiohttp.

## Authentication

A RunPod proxy URL may be accessible to other people. Snapshot capture,
restore and upload requests therefore require a per-pod secret token.

By default it is generated automatically on first access and saved in:

    /workspace/.pod-state/workspace-snapshot/auth-token

Read the token in your pod shell:

    cat /workspace/.pod-state/workspace-snapshot/auth-token

Paste it into the frontend when prompted. The frontend holds it in the
current browser tab's sessionStorage only. Optionally set
COMFY_WORKSPACE_SNAPSHOT_TOKEN in ComfyUI's server environment.

Never include this token in a repository, shared URL or screenshot.

## Create a workspace snapshot

1. Open the workflows you want to preserve in ComfyUI.
2. Click "Workspace Snapshot" at the lower right (or use the ComfyUI command).
3. Select a name, group, tag, and which server directories to archive.
4. Choose "Capture tabs locally" to save a checkpoint without uploading, or
   "Capture + HF snapshot" to upload the checkpoint and selected files.

The frontend visits each open workflow tab sequentially and serializes the
live graph. It restores the originally active tab at the end. If any tab
fails to capture, no Hugging Face upload starts.

A checkpoint is written under:

    /workspace/ComfyUI/user/default/workspace_sessions/<session-id>.json

The backend then calls snapshot-pod with known, validated paths; the frontend
cannot supply an executable or an arbitrary filesystem path. Its default
selection is the checkpoint JSON, ComfyUI input, output_gpu0, saved workflows,
Tab Manager's server-backed settings and ComfyUI settings. The output directory
is opt-in because it can be very large.

The snapshot engine builds a temporary archive of the selected data, so free
disk space for another copy is required during an upload.

## Restore on a new pod

Restore the desired snapshot group with:

    configure-pod comfy-workspace --snapshot latest

Once ComfyUI is running with this extension installed, open Workspace
Snapshots, refresh saved sessions, select the restored checkpoint and click
"Restore selected session".

Every captured graph opens as a separate tab. Original saved workflow JSONs
are **not overwritten**; the original active tab is reselected when the
frontend supports it.

The Tab Manager layout file is also part of the backup:

    /workspace/ComfyUI/user/default/ComfyUI-Tab-Manager/settings.json

Tab Manager owns grouping and appearance. Its "Restore Saved Workflow Tabs"
feature can restore original saved-workflow paths, including group associations.
Temporary restored tabs use new paths, so their previous group assignments
may need to be applied manually.

## Limitations

- Queued or running GPU jobs, model weights, GPU memory and live previews
  are not checkpointed.
- Canvas zoom/pan can only be restored if included in serialized graph data.
- The browser must be open to capture unsaved edits; a shell-only backup
  cannot see unsaved browser drafts.
- Browser frontend APIs change. If native workflow activation or graph
  loading fails, the extension shows an error instead of claiming success.
- State outside /workspace cannot currently be archived by snapshot-pod.
  The default ComfyUI profile is used unless
  COMFY_WORKSPACE_SNAPSHOT_PROFILE is configured.
- Restoring the same session more than once creates additional duplicate tabs.
- Session JSON may contain sensitive prompts. Use a private Hugging Face repo
  when appropriate.

## Endpoints

- GET  /pod_runtime/workspace_snapshot/health (readiness only)
- POST /pod_runtime/workspace_snapshot/session
- GET  /pod_runtime/workspace_snapshot/sessions
- GET  /pod_runtime/workspace_snapshot/sessions/<id>
- POST /pod_runtime/workspace_snapshot/snapshot
- GET  /pod_runtime/workspace_snapshot/jobs/<id>

All endpoints except health require the X-Workspace-Snapshot-Token HTTP header.

The server validates session JSON, limits requests to 32 MiB and 120 tabs,
validates group names, selects archive paths server-side, and permits only
one concurrent upload per ComfyUI process.

## Tests

    python3 -m unittest discover -s tests -p 'test_workspace_snapshot_node.py' -v


## Custom-node environment checkpoints

**Capture + HF snapshot** now includes a **Custom-node environment + pending set**
checkbox, enabled by default. The collector reads the real installed custom
node folders and the manifest used by install_custom_nodes. It does not
install plugins or change their checkouts during capture.

The tool compares active manifest definitions with the installed Git remotes
and supplements its inventory with installer status data. Newly discovered
Git repositories with a usable remote and commit are added to the snapshot
copy's pending set. Existing node definitions retain their pip/clone overrides
and are pinned to the observed Git commit in the **snapshot copy**.

These files are included in the same Hugging Face archive:

    /workspace/.pod-state/custom_nodes/manifest.json
    /workspace/.pod-state/custom_nodes/inventory.json
    /workspace/.pod-state/custom_nodes/packages.json

inventory.json records installed revisions, dirty state and unresolved
non-Git folders. packages.json records Python package versions for diagnosis,
but is not replayed as pip requirements automatically. Local uncommitted code,
non-Git folders, unsupported Git remotes and manually installed packages
may require manual reconstruction. Warnings are included with the job result.

### Restore all parts of a workspace on a new pod

Supply these variables **to the pod launcher before start.sh**:

    POD_RESTORE_GROUP=comfy-workspace
    POD_RESTORE_SNAPSHOT=latest

An exact snapshot ID can be used instead of latest. On an explicit restore,
start.sh downloads the selected snapshot after hf-tools installation and
before installing custom nodes. It validates the archived manifest and selects
the pending set alongside originally selected optional sets. The existing
launcher/main manifest is left untouched.

**Normal startup never selects a previously restored manifest automatically.**
If an explicitly requested snapshot lacks a manifest or cannot be validated,
startup stops rather than silently installing a different set of nodes.

A full snapshot with large output folders must be downloaded and extracted
before custom-node installation on the new pod. For software-only recovery,
create a snapshot with image directories deselected.

### Inspect and promote pending nodes

Preview installed vs managed nodes without writing files:

    python3 /workspace/pod-runtime/bin/custom_node_snapshot.py discover --dry-run

Create a local, snapshot-specific manifest and inventory without uploading:

    python3 /workspace/pod-runtime/bin/custom_node_snapshot.py discover

Promote a tested pending node into the checked-out primary manifest:

    python3 /workspace/pod-runtime/bin/custom_node_snapshot.py promote comfyui-new --set krea2

This writes /workspace/pod-runtime/custom_nodes_manifest.json locally, without
modifying the snapshot's historical pending set. Review and commit/push the
main manifest separately. Existing definitions are never silently replaced.


### One-shot restoration behavior

After a successful snapshot reconstruction and custom-node installation,
start.sh records a receipt under /workspace/.pod-state/restore-receipts/.
If the same container restarts with the same restore environment variables,
the receipt prevents downloading and installing from that snapshot again.
That restart follows the normal launcher manifest instead. The receipt is
stored outside archived custom-node state and will not be copied to new pods.

To deliberately repeat the restore in that container, supply
POD_RESTORE_FORCE=true along with POD_RESTORE_SNAPSHOT. Removing the receipt
also allows retrying. Failed plugin installations do not create a receipt.

