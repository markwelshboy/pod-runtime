# Custom-node installer profiling

The normal `install_custom_nodes` path uses `bin/custom_nodes_profiled.py`, a thin profiling wrapper around `bin/custom_nodes.py`. Profiling is automatic and does not change node selection, Git behavior, dependency handling, or failure semantics.

## Files

By default, profiles are stored beneath the custom-node log directory:

```text
/workspace/logs/custom_nodes/
├── install_status.json
└── profiles/
    ├── latest.json
    ├── history.jsonl
    └── run-<UTC timestamp>-<pid>.json
```

Environment overrides:

```bash
CUSTOM_NODE_STATUS_FILE=/path/install_status.json
CUSTOM_NODE_PROFILE_DIR=/path/profiles
CUSTOM_NODE_PROFILE_KEEP_RUNS=50
```

`history.jsonl` is append-only. On disposable pods, copy or include the profile directory in the existing end-of-session snapshot before terminating the pod. Point `CUSTOM_NODE_PROFILE_DIR` at a persistent/snapshotted path when that is more convenient.

## Captured measurements

Run-level data includes:

- wall-clock duration;
- parallel Git phase wall time;
- summed Git work across nodes;
- sequential dependency-install phase time;
- selected sets and environment identity.

Per node, the profiler records:

- Git clone/update time and subcommands;
- previous/current commit and whether an in-place checkout changed;
- effective requirements count and fingerprint;
- pip execution time;
- `install.py` execution time;
- observed pip cache hits;
- observed download count and sizes printed by pip;
- observed wheel builds and successful installs;
- total node preparation time and success/failure state.

Download-byte values are parsed from pip's human-readable output. They are useful for comparisons but may undercount streamed or unlabelled transfers.

## View the current run

```bash
custom_node_manifest status
```

The status output includes Git, pip, `install.py`, and total seconds per node.

## Compare several pod sessions

```bash
custom_node_manifest profile
```

Useful options:

```bash
# Last 50 sessions
custom_node_manifest profile --runs 50

# Only nodes observed at least three times
custom_node_manifest profile --runs 50 --min-runs 3

# Machine-readable aggregate across all retained history
custom_node_manifest profile --runs 0 --json
```

The report ranks nodes using observed use frequency and median startup cost. Its final column is deliberately heuristic:

- `compiled bundle`: wheel compilation or a long `install.py` stage was observed;
- `keep live/update`: the observed checkout commit changes frequently;
- `pip/wheel cache`: pip is consistently expensive without a stronger compilation signal;
- `source cache`: Git transfer is expensive and the checkout appears relatively stable;
- `runtime install`: no strong caching/bundling signal yet;
- `collect more data`: fewer than three observations exist.

A fast-moving project such as KJNodes should naturally trend toward `keep live/update`, even when it appears in nearly every session. The change rate considers both updates within a persistent checkout and commit transitions between separate pod sessions. The profiler supports a decision; it never automatically pins, bundles, or excludes a node.
