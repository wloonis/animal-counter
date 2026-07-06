#!/usr/bin/env python3
"""One-shot migration of docs/09_backlog.md to-do items -> GitHub Issues.

- Creates the label set (idempotent).
- Parses the recap table + detail sections.
- Creates one issue per ⬜ to-do BL (title, body, labels: backlog + P0/P1/P2 +
  category + S/M/L), capturing the issue number.
- Rewrites the recap table to link BL-XX -> its issue for the to-do rows.
- Prints a BL -> issue map.

Re-run-safe: it re-creates issues (no de-dup) — only run once per migration.
"""
import re, subprocess, json, sys, time

REPO = "wloonis/animal-counter"
DOC = "docs/09_backlog.md"

LABEL_COLORS = {
    "backlog":       "ededed",
    "P0":            "b60205", "P1": "d93f0b", "P2": "fbca04",
    "S":             "c2e0c6", "M": "fef2c0", "L": "f9d0c4",
    "robustness":    "1d76db", "security": "d4c5f9", "ops": "c5def5",
    "observability":"006b75", "architecture":"5319e7", "performance":"0052cc",
    "testability":   "0e8a16", "documentation":"0075ca",
}

def gh(*args, capture=True, check=True):
    r = subprocess.run(["gh", *args], capture_output=capture, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {args[:2]} failed:\n{r.stderr}")
    return r.stdout

def create_labels():
    for name, color in LABEL_COLORS.items():
        # --force recreates (idempotent on re-run after a partial run)
        gh("label", "create", name, "--color", color, "-R", REPO,
           "--force", check=False)

def parse_backlog(path):
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    recap = {}   # BL-XX -> dict(title, category, priority, size, status, recap_line_idx)
    detail = {}  # BL-XX -> body
    # recap table
    for i, ln in enumerate(lines):
        m = re.match(r"^\|\s*(BL-\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(P[012])\s*\|\s*([SML])\s*\|\s*(.)\s*\|\s*(.+?)\s*\|$", ln)
        if m:
            bl, title, cat, pri, size, color, status = m.groups()
            recap[bl] = dict(title=title.strip(), category=cat.strip(),
                             priority=pri, size=size, status=status.strip(),
                             idx=i)
    # detail sections
    cur_bl = None; cur_body = []
    for ln in lines:
        hm = re.match(r"^### ⬜ BL-(\d+) — (.+)$", ln)
        if hm:
            if cur_bl:
                detail[cur_bl] = "\n".join(cur_body).strip()
            cur_bl = "BL-" + hm.group(1)
            cur_body = []
        elif re.match(r"^### ", ln) or re.match(r"^## ", ln):
            if cur_bl:
                detail[cur_bl] = "\n".join(cur_body).strip()
                cur_bl = None; cur_body = []
        elif cur_bl:
            cur_body.append(ln)
    if cur_bl:
        detail[cur_bl] = "\n".join(cur_body).strip()
    return lines, recap, detail

def clean_title(title):
    # strip trailing ⭐/⭐⭐ and whitespace
    return title.replace("⭐","").strip().rstrip(".").strip()

def create_issue(bl, meta, body):
    title = f"{bl} — {clean_title(meta['title'])}"
    labels = ["backlog", meta["priority"], meta["category"].lower(), meta["size"]]
    full_body = (body or "_(No detail section in docs/09_backlog.md — see the file.)_"
                 + f"\n\n---\n_From [`docs/09_backlog.md`](docs/09_backlog.md) "
                 f"· {meta['priority']} · {meta['size']} · {meta['category']}_")
    # write body to a temp arg via stdin to avoid shell quoting
    r = subprocess.run(
        ["gh", "issue", "create", "-R", REPO,
         "--title", title, "--label", ",".join(labels),
         "--body-file", "-"],
        input=full_body, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  !! create failed for {bl}: {r.stderr}", file=sys.stderr)
        return None
    url = r.stdout.strip().splitlines()[-1]
    # fetch the number
    num = gh("issue", "view", url, "-R", REPO, "--json", "number", "-q", ".number").strip()
    return num, url

def main():
    print(">> creating labels (idempotent)…")
    create_labels()
    print(">> parsing backlog…")
    lines, recap, detail = parse_backlog(DOC)
    todo = {bl: m for bl, m in recap.items() if m["status"] == "⬜ to do"}
    print(f"   {len(todo)} to-do items, {len(recap)} total, {len(detail)} detail sections")
    mapping = {}
    print(">> creating issues…")
    for bl in sorted(todo, key=lambda b: int(b.split("-")[1])):
        meta = todo[bl]
        body = detail.get(bl, "")
        if not body:
            print(f"   {bl}: no detail body, using placeholder")
        res = create_issue(bl, meta, body)
        if res:
            num, url = res
            mapping[bl] = (num, url)
            print(f"   {bl}: #{num}")
        else:
            print(f"   {bl}: FAILED")
        time.sleep(0.3)  # be gentle to the API
    # rewrite the recap table to link BL-XX -> issue
    print(">> linking recap table…")
    for bl, (num, url) in mapping.items():
        i = todo[bl]["idx"]
        ln = lines[i]
        ln2 = ln.replace(f"| {bl} |", f"| [{bl}]({url}) |", 1)
        lines[i] = ln2
    open(DOC, "w", encoding="utf-8").write("\n".join(lines))
    print(f">> done: {len(mapping)} issues created + linked in {DOC}")
    # save map for reference
    with open("/tmp/bl_issue_map.json", "w") as f:
        json.dump({bl: dict(number=n, url=u) for bl, (n, u) in mapping.items()}, f, indent=2)
    print("   map -> /tmp/bl_issue_map.json")

if __name__ == "__main__":
    main()