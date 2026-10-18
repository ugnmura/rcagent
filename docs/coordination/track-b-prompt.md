# Prompt for a Claude joining the bench track

Give this to Claude Code in a checkout of `ugnmura/serenedb-bench`. It works for anyone joining at any time (Nonaim, Eugene, or a second session of the same person).

---

You are joining an ongoing, time-boxed piece of work: running the RCAEval root-cause benchmark against the SereneDB extractor's new metric and trace tools. Several people's Claude sessions work on it at the same time. Coordinate only through GitHub issue <ISSUE URL> in ugnmura/serenedb-bench.

Before anything else:

1. Read the issue and all its comments. Read the data contract `docs/contracts/telemetry-case-v1.md` and the design `docs/superpowers/specs/2026-10-18-metrics-traces-design.md` in ugnmura/serenedb-extractor, branch `feat/metrics-traces` (`gh api` or a fetch of that branch). Read `harness/README.md` in this repo.
2. Tell me (the human) which units are open, which one you propose to take, and why. Wait for my OK.
3. Claim it with an issue comment `claim <unit> (<my GitHub name>, <machine>)`. If someone else's claim is already there, pick another unit.

While working:

- Work on branch `bench/<unit>`. Commit in small steps. Never push to `main`; ask me before any push.
- Post a short progress comment at least every 45 minutes (what is done, what is next, blockers). A unit with no comment for 45 minutes counts as open again.
- Follow the issue's rules exactly. The ones that matter most: labels never reach the agent (neutral folders, table names, paths, metric names; labels outside the data root); no tuning on RCAEval; at most 2 scored runs on the test set; every score carries a comparability note.
- SereneDB must run on an amd64 host (26.10.1 crashes under emulation on Apple Silicon). Use this machine if it is amd64, otherwise a tunnel to an amd64 host. Don't run more SereneDB containers than the host's RAM allows; say what you used.
- If the contract does not fit the data, do not change it on your own: post the problem in the issue and continue with another unit.
- If something is unclear, ask in the issue and tell me; don't guess on anything that affects scores.

When the unit is done: post a comment with what was done, the branch and commit, how to reproduce, and anything the next person must know. Update the unit's status in your comment (`done B1 @ <commit>`). Then report to me and propose the next open unit.
