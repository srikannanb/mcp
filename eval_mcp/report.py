from .evaluator import EvalResult


def render_html(results: list, output_path: str) -> None:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    pct = int(passed / total * 100) if total else 0

    rows = []
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        badge_color = "#2d6a4f" if r.passed else "#9b2226"
        row_bg = "#d8f3dc" if r.passed else "#ffe0e0"
        rows.append(f"""
        <tr style="background:{row_bg}">
            <td>{_esc(r.prompt)}</td>
            <td>{_esc(r.expected)}</td>
            <td>{_esc(r.actual)}</td>
            <td><span style="color:{badge_color};font-weight:bold">{status}</span></td>
        </tr>
        <tr style="background:{row_bg}">
            <td colspan="4">
                <details>
                    <summary>Tool descriptions</summary>
                    <p><strong>Expected ({_esc(r.expected)}):</strong> {_esc(r.expected_description)}</p>
                    <p><strong>Actual ({_esc(r.actual)}):</strong> {_esc(r.actual_description)}</p>
                </details>
            </td>
        </tr>""")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>MCP Eval Report</title>
<style>
body {{font-family: sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem}}
table {{border-collapse: collapse; width: 100%}}
th, td {{border: 1px solid #ccc; padding: .5rem .75rem; text-align: left}}
th {{background: #f0f0f0}}
.score {{font-size: 1.5rem; font-weight: bold; margin-bottom: 1rem}}
details summary {{cursor: pointer}}
</style>
</head>
<body>
<h1>MCP Readiness Eval Report</h1>
<p class="score">{passed} / {total} passed &mdash; {pct}%</p>
<table>
<thead>
<tr><th>Prompt</th><th>Expected</th><th>Actual</th><th>Result</th></tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )
