# Hugging Face manifest tree mode

Manifest sections retain their existing selection behavior. A section such as
`download_krea2` is enabled with the same Bash/environment variable:

```bash
export download_krea2=true
```

Entries without `mode`, or with `"mode": "file"`, retain the existing one-entry,
one-file behavior.

## Tree entry

```json
{
  "id": "diffusionetc-krea2-loras",
  "mode": "tree",
  "repo_id": "markwelshboyx/diffusionetc",
  "repo_type": "model",
  "revision": "main",
  "include": [
    "models/loras/krea2/*.safetensors"
  ],
  "exclude": [
    "**/*.md"
  ],
  "strip_prefix": "models/loras/krea2",
  "path": "{LORAS_DIR}/Krea-2"
}
```

The planner lists the selected Hugging Face subtree and expands the declaration
into ordinary per-file items before downloading. Existing status behavior is
therefore preserved: each file has its own expected size, destination, log,
completion state, and retry/failure result.

## Fields

- `id`: Optional source label used in expansion messages.
- `mode`: Must be `tree`.
- `repo_id`: Hugging Face repository in `owner/name` form.
- `repo_type`: `model` by default; `dataset` and `space` are also accepted.
- `revision`: Branch, tag, or commit; defaults to `main`.
- `include`: String or list of remote-path glob patterns. Defaults to `**`.
- `exclude`: Optional string or list of remote-path glob patterns.
- `strip_prefix`: Remote prefix removed before constructing the destination.
  It is also used to limit the Hub tree query to that subtree.
- `path`: Local destination root. Manifest placeholders are resolved normally.
- `flatten`: Optional boolean. When true, only each remote basename is retained.
  Duplicate destination names are rejected.
- `allow_empty`: Optional boolean. By default, a tree matching no files fails
  manifest planning; set this true when an empty match is acceptable.

## Path mapping

For this declaration:

```json
{
  "mode": "tree",
  "repo_id": "markwelshboyx/diffusionetc",
  "include": [
    "models/loras/characters/siobhan/krea2/training/*.safetensors"
  ],
  "strip_prefix": "models/loras/characters/siobhan/krea2/training",
  "path": "{LORAS_DIR}/characters/siobhan/krea2"
}
```

A remote file:

```text
models/loras/characters/siobhan/krea2/training/example.safetensors
```

is written to:

```text
{LORAS_DIR}/characters/siobhan/krea2/example.safetensors
```

File and tree entries can be freely mixed in the same section. Third-party
repositories can remain as explicit file entries when only selected files from
a larger repository are wanted.
