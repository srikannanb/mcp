import json

from .stability import StabilityResult


def render_html(results: list, output_path: str) -> None:
    total = len(results)
    stable_pass = sum(1 for r in results if r.pass_rate == 1.0)
    stable_fail = sum(1 for r in results if r.pass_rate == 0.0)
    flaky = total - stable_pass - stable_fail
    mean_rate_pct = int(sum(r.pass_rate for r in results) / total * 100) if total else 0

    rows = []
    for r in results:
        status, row_bg, badge_color = _status_for(r.pass_rate)
        rows.append(f"""
        <tr style="background:{row_bg}">
            <td>{_esc(r.prompt)}</td>
            <td>{_esc(r.expected)}</td>
            <td>{_format_picks(r.picks, r.expected)}</td>
            <td>{r.passes}/{r.runs}</td>
            <td>{int(r.pass_rate * 100)}%</td>
            <td><span style="color:{badge_color};font-weight:bold">{status}</span></td>
        </tr>
        <tr style="background:{row_bg}">
            <td colspan="6">
                <details>
                    <summary>Details</summary>
                    <p><strong>Expected description:</strong> {_esc(r.expected_description)}</p>
                    <p><strong>Params from passing runs:</strong></p>
                    <pre>{_esc(_format_params_list(r.extracted_params))}</pre>
                </details>
            </td>
        </tr>""")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>MCP Stability Report</title>
<style>
body {{font-family: sans-serif; max-width: 1200px; margin: 2rem auto; padding: 0 1rem}}
table {{border-collapse: collapse; width: 100%}}
th, td {{border: 1px solid #ccc; padding: .5rem .75rem; text-align: left; vertical-align: top}}
th {{background: #f0f0f0}}
.summary {{display: flex; gap: 2rem; margin: 1rem 0 1.5rem 0}}
.summary div {{padding: .5rem 1rem; border: 1px solid #ddd; border-radius: 4px; background: #fafafa}}
.summary strong {{display: block; font-size: 1.6rem; line-height: 1.2}}
.summary span {{color: #555; font-size: .9rem}}
details summary {{cursor: pointer}}
.pick {{display: inline-block; margin: .15rem .25rem .15rem 0; padding: .1rem .4rem; border-radius: 3px; background: #eee; font-family: monospace; font-size: .9rem}}
.pick-expected {{background: #c8e6c9}}
.pick-error {{background: #ffcdd2}}
</style>
</head>
<body>
<h1>MCP Stability Report</h1>
<div class="summary">
    <div><strong>{mean_rate_pct}%</strong><span>mean pass rate</span></div>
    <div><strong>{stable_pass}/{total}</strong><span>stable-pass</span></div>
    <div><strong>{flaky}</strong><span>flaky</span></div>
    <div><strong>{stable_fail}</strong><span>stable-fail</span></div>
</div>
<table>
<thead>
<tr><th>Prompt</th><th>Expected</th><th>Picks (histogram)</th><th>Passes</th><th>Pass rate</th><th>Status</th></tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)


def _status_for(rate: float):
    if rate == 1.0:
        return "STABLE-PASS", "#d8f3dc", "#2d6a4f"
    if rate == 0.0:
        return "STABLE-FAIL", "#ffe0e0", "#9b2226"
    return "FLAKY", "#fff4d6", "#8a5a00"


def _format_picks(picks: dict, expected: str) -> str:
    if not picks:
        return ""
    items = sorted(picks.items(), key=lambda kv: -kv[1])
    pieces = []
    for name, count in items:
        cls = "pick"
        if name == expected:
            cls += " pick-expected"
        elif name == "ERROR":
            cls += " pick-error"
        pieces.append(f'<span class="{cls}">{_esc(name)} &times; {count}</span>')
    return "".join(pieces)


def _format_params_list(params_list: list) -> str:
    if not params_list:
        return "(no passing runs)"
    return "\n".join(json.dumps(p, sort_keys=True) for p in params_list)


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )
