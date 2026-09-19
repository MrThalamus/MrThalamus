#!/usr/bin/env python3
"""Generate the GitHub stats cards (dark + light SVG) embedded in README.md.

Needs GH_TOKEN (or GITHUB_TOKEN) in the environment. Uses only the standard library.
Edit stats_config.json to change the username or how repos map to categories.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("stats_config.json")
OUT_DIR = Path(__file__).resolve().parents[2] / "assets"
GRAPHQL_URL = "https://api.github.com/graphql"

THEMES = {
    "dark": {"card": "#0d1117", "border": "#30363d", "text": "#e6edf3", "muted": "#8b949e"},
    "light": {"card": "#ffffff", "border": "#d0d7de", "text": "#1f2328", "muted": "#656d76"},
}

WIDTH = 830
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


# ---------------------------------------------------------------- data fetching

def graphql(query, variables, token):
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL error: {payload['errors']}")
    return payload["data"]


PROFILE_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    issues { totalCount }
    pullRequests { totalCount }
    repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, PULL_REQUEST_REVIEW]) { totalCount }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false, first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        description
        stargazerCount
        repositoryTopics(first: 20) { nodes { topic { name } } }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

YEAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch_profile(login, token):
    """Account-level counters plus every public, non-fork repo."""
    repos, cursor, profile = [], None, None
    while True:
        user = graphql(PROFILE_QUERY, {"login": login, "cursor": cursor}, token)["user"]
        profile = profile or user
        page = user["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return profile, repos
        cursor = page["pageInfo"]["endCursor"]


def fetch_contributions(login, created_at, token):
    """Lifetime commit/contribution totals and per-day counts (API allows 1 year per call)."""
    now = datetime.now(timezone.utc)
    commits = total = 0
    days = {}
    for year in range(int(created_at[:4]), now.year + 1):
        variables = {"login": login, "from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"}
        collection = graphql(YEAR_QUERY, variables, token)["user"]["contributionsCollection"]
        commits += collection["totalCommitContributions"]
        calendar = collection["contributionCalendar"]
        total += calendar["totalContributions"]
        for week in calendar["weeks"]:
            for day in week["contributionDays"]:
                days[date.fromisoformat(day["date"])] = day["contributionCount"]
    return commits, total, days


# -------------------------------------------------------------------- analysis

def streaks(days, today):
    """Return (current, longest) streak lengths in days."""
    longest = run = 0
    for day in sorted(days):
        if day > today:
            continue
        run = run + 1 if days[day] > 0 else 0
        longest = max(longest, run)

    current = 0
    day = today if days.get(today, 0) > 0 else today - timedelta(days=1)  # today may not be over yet
    while days.get(day, 0) > 0:
        current += 1
        day -= timedelta(days=1)
    return current, longest


def categorize(repo, config):
    topics = [node["topic"]["name"] for node in repo["repositoryTopics"]["nodes"]]
    text = re.sub(r"[-_]+", " ", " ".join([repo["name"], repo["description"] or "", *topics])).lower()
    edges = repo["languages"]["edges"]
    primary_language = edges[0]["node"]["name"] if edges else None

    for category in config["categories"]:
        if primary_language in category["languages"] or any(re.search(p, text) for p in category["match"]):
            return category["name"]
    return config["fallback_category"]["name"]


def category_counts(repos, config):
    counts = {}
    for repo in repos:
        name = categorize(repo, config)
        counts[name] = counts.get(name, 0) + 1
    colors = {c["name"]: c["color"] for c in config["categories"]}
    colors[config["fallback_category"]["name"]] = config["fallback_category"]["color"]
    order = [c["name"] for c in config["categories"]] + [config["fallback_category"]["name"]]
    return [(name, counts[name], colors[name]) for name in order if name in counts]


def language_shares(repos, config):
    sizes, colors = {}, {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in config["exclude_languages"]:
                continue
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or "#8b949e"
    total = sum(sizes.values()) or 1
    top = sorted(sizes, key=sizes.get, reverse=True)[: config["top_languages"]]
    return [(name, sizes[name] / total * 100, colors[name]) for name in top]


def collect_stats(config, token):
    login = config["username"]
    profile, repos = fetch_profile(login, token)
    repos = [r for r in repos if r["name"] not in config["exclude_repos"]]
    commits, contributions, days = fetch_contributions(login, profile["createdAt"], token)
    current, longest = streaks(days, datetime.now(timezone.utc).date())
    return {
        "contributions": contributions,
        "commits": commits,
        "pull_requests": profile["pullRequests"]["totalCount"],
        "issues": profile["issues"]["totalCount"],
        "contributed_to": profile["repositoriesContributedTo"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "followers": profile["followers"]["totalCount"],
        "current_streak": current,
        "longest_streak": longest,
        "projects": len(repos),
        "categories": category_counts(repos, config),
        "languages": language_shares(repos, config),
    }


# ------------------------------------------------------------------- rendering

def days_label(n):
    return f"{n} day" if n == 1 else f"{n} days"


def card(y, height, theme):
    return (f'<rect x="1" y="{y}" width="{WIDTH - 2}" height="{height}" rx="8" '
            f'fill="{theme["card"]}" stroke="{theme["border"]}" stroke-width="1"/>')


def title(y, text, theme, right=None):
    out = f'<text x="32" y="{y + 44}" font-size="20" font-weight="600" fill="{theme["text"]}">{escape(text)}</text>'
    if right:
        out += (f'<text x="{WIDTH - 32}" y="{y + 44}" font-size="14" text-anchor="end" '
                f'fill="{theme["muted"]}">{escape(right)}</text>')
    return out


def stats_card(y, stats, theme):
    cells = [
        (f"{stats['contributions']:,}", "Total contributions"),
        (f"{stats['commits']:,}", "Commits"),
        (f"{stats['pull_requests']:,}", "Pull requests"),
        (f"{stats['issues']:,}", "Issues"),
        (f"{stats['contributed_to']:,} repos", "Contributed to"),
        (f"{stats['stars']:,}", "Stars earned"),
        (f"{stats['followers']:,}", "Followers"),
        (days_label(stats["current_streak"]), "Current streak"),
        (days_label(stats["longest_streak"]), "Longest streak"),
    ]
    height = 318
    out = [card(y, height, theme), title(y, "GitHub stats", theme)]
    for i, (value, label) in enumerate(cells):
        x, top = 32 + (i % 3) * 312, y + 108 + (i // 3) * 78
        out.append(f'<text x="{x}" y="{top}" font-size="28" font-weight="600" fill="{theme["text"]}">{escape(value)}</text>')
        out.append(f'<text x="{x}" y="{top + 22}" font-size="14" fill="{theme["muted"]}">{escape(label)}</text>')
    return "\n".join(out), height


def breakdown_card(y, heading, right, items, clip_id, theme):
    """A segmented bar plus a 3-column legend. items = [(label, weight, color, detail)]."""
    rows = -(-len(items) // 3)
    height = 96 + rows * 30 + 12
    total = sum(weight for _, weight, _, _ in items) or 1
    bar_x, bar_w, bar_y = 32, WIDTH - 64, y + 66

    out = [card(y, height, theme), title(y, heading, theme, right),
           f'<clipPath id="{clip_id}"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="8" rx="4"/></clipPath>',
           f'<g clip-path="url(#{clip_id})">']
    x = bar_x
    for _, weight, color, _ in items:
        w = bar_w * weight / total
        out.append(f'<rect x="{x:.2f}" y="{bar_y}" width="{w:.2f}" height="8" fill="{color}"/>')
        x += w
    out.append("</g>")

    for i, (label, _, color, detail) in enumerate(items):
        lx, ly = 32 + (i % 3) * 312, y + 118 + (i // 3) * 30
        out.append(f'<circle cx="{lx + 6}" cy="{ly - 5}" r="6" fill="{color}"/>')
        out.append(f'<text x="{lx + 20}" y="{ly}" font-size="14" fill="{theme["text"]}">{escape(label)} '
                   f'<tspan fill="{theme["muted"]}">{escape(detail)}</tspan></text>')
    return "\n".join(out), height


def render(stats, theme):
    gap, y = 16, 1
    parts = []

    block, height = stats_card(y, stats, theme)
    parts.append(block)
    y += height + gap

    projects = [(name, count, color, str(count)) for name, count, color in stats["categories"]]
    block, height = breakdown_card(y, "Projects by category", f"{stats['projects']} projects", projects, "clip-cat", theme)
    parts.append(block)
    y += height + gap

    languages = [(name, pct, color, f"{pct:.1f}%") for name, pct, color in stats["languages"]]
    block, height = breakdown_card(y, "Top languages", None, languages, "clip-lang", theme)
    parts.append(block)
    y += height

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{y + 1}" viewBox="0 0 {WIDTH} {y + 1}" '
            f'font-family="{FONT}" role="img" aria-label="GitHub stats">\n' + "\n".join(parts) + "\n</svg>\n")


def main():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Set GH_TOKEN (or GITHUB_TOKEN) to a GitHub token.")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    stats = collect_stats(config, token)

    OUT_DIR.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (OUT_DIR / f"github-stats-{name}.svg").write_text(render(stats, theme), encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
