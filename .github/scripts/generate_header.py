#!/usr/bin/env python3
"""Generate the animated README header (dark + light SVG). No token or network needed.

Reads the "header" section of stats_config.json. Animation is pure SVG (SMIL), which GitHub
renders inside <img>: the name fades in, an underline draws, then each role is typed and erased.
"""
import json
from html import escape
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("stats_config.json")
OUT_DIR = Path(__file__).resolve().parents[2] / "assets"

THEMES = {
    "dark": {"text": "#e6edf3", "muted": "#8b949e", "from": "#58a6ff", "to": "#a371f7"},
    "light": {"text": "#1f2328", "muted": "#656d76", "from": "#0969da", "to": "#8250df"},
}

WIDTH, HEIGHT = 830, 190
CENTER = WIDTH / 2
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'SF Mono', Consolas, Menlo, 'Courier New', monospace"
ROLE_SIZE, CHAR_W = 22, 13.2     # monospace advance is ~0.6em; textLength pins it in any font
SLOT = 4.4                        # seconds each role stays on screen
START = 1.3                       # seconds before typing starts (after the intro)


def discrete(attribute, pairs, dur, begin):
    """A stepwise <animate>. pairs = [(fraction_of_cycle, value)]; later pairs win on equal times."""
    merged = {}
    for time, value in sorted(pairs, key=lambda p: p[0]):
        merged[round(time, 4)] = value
    times = sorted(merged)
    if times[-1] < 1:
        merged[1] = merged[times[-1]]
        times.append(1)
    key_times = ";".join(f"{t:g}" for t in times)
    values = ";".join(f"{merged[t]:g}" for t in times)
    return (f'<animate attributeName="{attribute}" calcMode="discrete" dur="{dur:g}s" begin="{begin:g}s" '
            f'repeatCount="indefinite" keyTimes="{key_times}" values="{values}"/>')


def role_markup(index, role, count, theme):
    n = len(role)
    x0 = CENTER - n * CHAR_W / 2
    total = SLOT * count
    t0 = index / count
    slot = 1 / count                     # fraction of the cycle for one role

    widths = [(t0 + (k - 1) / n * 0.4 * slot, k * CHAR_W) for k in range(1, n + 1)]      # type
    widths += [(t0 + (0.8 + (j - 1) / n * 0.2) * slot, (n - j) * CHAR_W) for j in range(1, n + 1)]  # erase
    shown = [(0, 0), (t0, 1), (t0 + slot, 0)]

    def with_zero(pairs):
        return pairs if t0 == 0 else [(0, 0)] + pairs

    clip_id = f"role{index}"
    return f"""
  <clipPath id="{clip_id}"><rect x="{x0:.1f}" y="140" width="0" height="34">
    {discrete("width", with_zero(widths), total, START)}
  </rect></clipPath>
  <text x="{x0:.1f}" y="166" font-family="{MONO}" font-size="{ROLE_SIZE}" fill="{theme["text"]}"
        textLength="{n * CHAR_W:.1f}" lengthAdjust="spacing" clip-path="url(#{clip_id})">{escape(role)}</text>
  <g opacity="0">
    {discrete("opacity", shown, total, START)}
    <rect y="144" width="2" height="26" fill="{theme["from"]}">
      {discrete("x", with_zero([(t, x0 + w + 3) for t, w in widths]), total, START)}
      <animate attributeName="opacity" calcMode="discrete" dur="1s" repeatCount="indefinite" keyTimes="0;0.5" values="1;0"/>
    </rect>
  </g>"""


def render(header, theme):
    roles = "".join(role_markup(i, r, len(header["roles"]), theme) for i, r in enumerate(header["roles"]))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(header["name"])}: {escape(", ".join(header["roles"]))}">
  <defs>
    <linearGradient id="name-gradient" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{CENTER:g}" y2="0" spreadMethod="reflect">
      <stop offset="0" stop-color="{theme["from"]}"/>
      <stop offset="1" stop-color="{theme["to"]}"/>
      <animateTransform attributeName="gradientTransform" type="translate" from="0 0" to="{WIDTH} 0" dur="8s" repeatCount="indefinite"/>
    </linearGradient>
  </defs>

  <g font-family="{FONT}" text-anchor="middle">
    <g opacity="0">
      <animate attributeName="opacity" from="0" to="1" dur="0.9s" begin="0.1s" fill="freeze"/>
      <animateTransform attributeName="transform" type="translate" from="0 14" to="0 0" dur="0.9s" begin="0.1s" fill="freeze"/>
      <text x="{CENTER:g}" y="48" font-size="18" fill="{theme["muted"]}">{escape(header["greeting"])}</text>
      <text x="{CENTER:g}" y="100" font-size="44" font-weight="700" fill="url(#name-gradient)">{escape(header["name"])}</text>
    </g>
  </g>

  <rect x="{CENTER:g}" y="120" width="0" height="3" rx="1.5" fill="url(#name-gradient)">
    <animate attributeName="x" from="{CENTER:g}" to="{CENTER - 110:g}" dur="0.9s" begin="0.6s" fill="freeze"/>
    <animate attributeName="width" from="0" to="220" dur="0.9s" begin="0.6s" fill="freeze"/>
  </rect>
{roles}
</svg>
"""


def main():
    header = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["header"]
    OUT_DIR.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (OUT_DIR / f"header-{name}.svg").write_text(render(header, theme), encoding="utf-8")
        print(f"wrote assets/header-{name}.svg")


if __name__ == "__main__":
    main()
