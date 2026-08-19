# Dependency automation ownership

Each versioned input has one automation owner. Human review remains the approval layer and automation never merges dependency changes automatically.

Renovate owns only pinned GitHub Actions, the pinned Dockerfile frontend, and the Ubuntu LTS version/digest pair. Ubuntu is updated exclusively by the bounded custom regex manager so `versions.env` and `images/base/Dockerfile` change atomically; the native Dockerfile Ubuntu match is disabled.

The scheduled `check-upstream.yml` workflow owns bundled runtime and tool pins, architecture hashes, mise configuration and lock data, notices, inventory, and standalone-artifact evidence. Native mise management remains disabled because those files must change as one validated set. Optional runtime availability and project image release references are outside Renovate ownership.

`scripts/validate-renovate-ownership.py` enforces this boundary offline. Adding another manager or transferring a dependency requires a focused review of this contract.
