"""Write a self-contained index.html that shows the profiles (works from file://)."""

import json
import os


def build(out_dir):
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "viewer.html"), encoding="utf-8") as handle:
        template = handle.read()
    profiles = []
    jsonl = os.path.join(out_dir, "profiles.jsonl")
    with open(jsonl, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                profiles.append(json.loads(line))
    report = {}
    report_path = os.path.join(out_dir, "run_report.json")
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as handle:
            report = json.load(handle)
    data = json.dumps({"profiles": profiles, "report": report}, ensure_ascii=False)
    data = data.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = template.replace("__DATA__", data)
    target = os.path.join(out_dir, "index.html")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(html)
    return target
