"""Local browser review tool for CV gesture logs.

Usage:
    python tools/review_gesture_samples.py
    python tools/review_gesture_samples.py --logs logs/cv_sessions/*.jsonl --port 8765
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cv.gesture_classifier import cv_path_length


DEFAULT_LOG_GLOB = "logs/cv_sessions/*.jsonl"
DEFAULT_OUTPUT = "models/gesture_reviewed_samples.jsonl"
LABELS = ("incendio", "circle", "glacius", "lumos", "overload")


def _copy_points(points):
    copied = []
    for point in points or []:
        try:
            if len(point) < 2:
                continue
            copied.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError, IndexError):
            continue
    return copied


def _suggested_label(entry):
    intended = entry.get("intended_spell")
    if intended in LABELS:
        return intended
    spell = (entry.get("primary") or {}).get("spell")
    if spell == "stupefy":
        return "circle"
    if spell in LABELS:
        return spell
    return None


def _validate_review_decision(label, review_status):
    if review_status not in ("accepted", "discarded", "skipped"):
        raise ValueError(f"unknown review status: {review_status}")
    if review_status == "accepted" and label not in LABELS:
        raise ValueError(f"unknown label: {label}")


def load_review_candidates(log_paths, min_path_length=55.0):
    """Load display-ready samples from CV session JSONL logs."""
    samples = []
    for log_path in log_paths:
        path = Path(log_path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            points = _copy_points(entry.get("points") or [])
            if len(points) < 2:
                continue
            path_length = float(entry.get("path_length") or cv_path_length(points))
            if path_length < float(min_path_length):
                continue
            attempt_id = entry.get("attempt_id", index + 1)
            sample = {
                "sample_id": entry.get("sample_id") or f"{path.name}:{attempt_id}",
                "source_file": str(path),
                "source_attempt_id": attempt_id,
                "timestamp": entry.get("timestamp"),
                "mode": entry.get("mode"),
                "side": entry.get("side"),
                "points": points,
                "path_length": path_length,
                "intended_spell": entry.get("intended_spell"),
                "suggested_label": _suggested_label(entry),
                "primary": entry.get("primary") or {},
                "cast_attempted": bool(entry.get("cast_attempted", False)),
                "cast_success": bool(entry.get("cast_success", False)),
                "debug_state": entry.get("debug_state"),
            }
            for name in (
                "schema",
                "session_id",
                "input_mode",
                "user_id",
                "device_id",
                "frame_width",
                "frame_height",
                "fps_estimate",
                "palm_scale",
                "classifier_version",
                "pipeline_version",
                "dataset_partition",
                "derived_from_sample_id",
            ):
                if entry.get(name) is not None:
                    sample[name] = entry[name]
            samples.append(sample)
    return samples


def append_review_record(output_path, sample, label, review_status):
    """Append one reviewed sample as JSONL and return the saved record."""
    _validate_review_decision(label, review_status)

    record = {
        "schema": 2,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "review_status": review_status,
        "label": label if review_status == "accepted" else None,
        "sample_id": sample.get("sample_id"),
        "source_file": sample.get("source_file"),
        "source_attempt_id": sample.get("source_attempt_id"),
        "mode": sample.get("mode"),
        "side": sample.get("side"),
        "points": _copy_points(sample.get("points") or []),
        "path_length": sample.get("path_length"),
        "intended_spell": sample.get("intended_spell"),
        "suggested_label": sample.get("suggested_label"),
        "primary": sample.get("primary") or {},
        "cast_success": bool(sample.get("cast_success", False)),
    }
    for name in (
        "session_id",
        "input_mode",
        "user_id",
        "device_id",
        "frame_width",
        "frame_height",
        "fps_estimate",
        "palm_scale",
        "classifier_version",
        "pipeline_version",
        "dataset_partition",
        "derived_from_sample_id",
    ):
        if sample.get(name) is not None:
            record[name] = sample[name]

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def commit_pending_reviews(output_path, samples_by_id, pending_reviews):
    """Persist pending browser decisions and return the saved records."""
    committed = []
    already_reviewed = load_reviewed_sample_ids(output_path)
    for sample_id, decision in list(pending_reviews.items()):
        if str(sample_id) in already_reviewed:
            continue
        sample = samples_by_id[sample_id]
        record = append_review_record(
            output_path,
            sample,
            decision.get("label"),
            decision.get("review_status", "accepted"),
        )
        already_reviewed.add(str(sample_id))
        committed.append(record)
    return committed


def load_reviewed_sample_ids(output_path):
    """Return sample ids that already have a review decision."""
    path = Path(output_path)
    if not path.exists():
        return set()
    reviewed = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return reviewed
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        sample_id = entry.get("sample_id")
        if sample_id:
            reviewed.add(str(sample_id))
    return reviewed


def filter_unreviewed_candidates(samples, output_path):
    return visible_review_samples(samples, output_path)


def visible_review_samples(samples, output_path, reviewed_ids=None, pending_reviews=None):
    reviewed = load_reviewed_sample_ids(output_path)
    reviewed.update(str(sample_id) for sample_id in (reviewed_ids or set()))
    pending_reviews = pending_reviews or {}
    visible = []
    for sample in samples:
        sample_id = str(sample.get("sample_id"))
        if sample_id in reviewed:
            continue
        item = dict(sample)
        pending = pending_reviews.get(sample_id)
        if pending:
            item["pending_label"] = pending.get("label")
            item["pending_review_status"] = pending.get("review_status")
        visible.append(item)
    return visible


def run_retrain(args=None):
    """Run the template training script and capture its console output."""
    from tools.retrain_gesture_templates import main as retrain_main

    retrain_args = [] if args is None else list(args)
    stream = io.StringIO()
    try:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            exit_code = retrain_main(retrain_args)
    except SystemExit as exc:
        exit_code = int(exc.code or 0)
    except Exception as exc:
        stream.write(f"\nTemplate pack rebuild failed: {exc}\n")
        return {
            "ok": False,
            "exit_code": 1,
            "output": stream.getvalue(),
        }
    return {
        "ok": int(exit_code) == 0,
        "exit_code": int(exit_code),
        "output": stream.getvalue(),
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Gesture Review</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #111318;
      --panel: #191d25;
      --line: #2d3442;
      --text: #eef2f7;
      --muted: #9aa6b6;
      --accent: #62c6ff;
      --good: #80d982;
      --bad: #ff7373;
    }
    * { box-sizing: border-box; }
    html { height: 100%; }
    body {
      margin: 0;
      height: 100vh;
      min-height: 100vh;
      overflow: hidden;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", Arial, sans-serif;
    }
    .app {
      display: grid;
      grid-template-columns: minmax(360px, 1fr) 340px;
      gap: 12px;
      padding: 12px;
      height: 100vh;
      min-height: 0;
      overflow: hidden;
    }
    .stage, .side {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .stage {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      min-height: 0;
      overflow: hidden;
    }
    header, .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
    }
    .heading {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 14px;
    }
    .legend {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 13px;
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      white-space: nowrap;
    }
    .legend-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
    }
    .legend-dot.start { background: var(--good); }
    .legend-dot.end { background: var(--bad); }
    .toolbar { border-top: 1px solid var(--line); border-bottom: 0; flex-wrap: wrap; }
    h1 { font-size: 18px; margin: 0; font-weight: 650; }
    .muted { color: var(--muted); font-size: 13px; }
    canvas { width: 100%; height: 100%; min-height: 300px; display: block; }
    .side { padding: 12px; overflow: hidden; min-height: 0; }
    .kv { display: grid; grid-template-columns: 86px 1fr; gap: 6px; margin: 10px 0; font-size: 13px; }
    .kv div:nth-child(odd) { color: var(--muted); }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 3px 7px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 12px;
      margin: 2px 4px 2px 0;
    }
    button {
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #242b37;
      color: var(--text);
      min-height: 34px;
      padding: 7px 9px;
      cursor: pointer;
      font-weight: 600;
    }
    button:hover { border-color: var(--accent); }
    button.primary { background: #173a4d; border-color: #286b8d; }
    button.bad { background: #4b2024; border-color: #7c3038; }
    button.ghost { background: transparent; }
    button.selected {
      border-color: var(--good);
      box-shadow: 0 0 0 2px rgba(128, 217, 130, 0.35);
    }
    button.bad.selected {
      border-color: var(--bad);
      box-shadow: 0 0 0 2px rgba(255, 115, 115, 0.32);
    }
    .labels { display: grid; grid-template-columns: repeat(5, minmax(80px, 1fr)); gap: 6px; flex: 1 1 420px; }
    .nav { display: flex; gap: 6px; }
    .prediction { padding: 8px; border: 1px solid var(--line); border-radius: 7px; margin: 6px 0; font-size: 13px; }
    .prediction strong { display: block; margin-bottom: 4px; }
    .side-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }
    .status {
      min-height: 18px;
      margin-bottom: 8px;
      font-size: 12px;
      color: var(--muted);
    }
    @media (max-width: 900px) {
      body { overflow: auto; }
      .app { grid-template-columns: 1fr; height: auto; min-height: 100vh; overflow: visible; }
      .labels { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .side { overflow: visible; }
    }
  </style>
</head>
<body>
  <main class="app">
    <section class="stage">
      <header>
        <div class="heading">
          <h1>Gesture Review</h1>
          <div class="legend" aria-label="trajectory legend">
            <span><i class="legend-dot start"></i>Start</span>
            <span><i class="legend-dot end"></i>End</span>
          </div>
        </div>
        <div class="muted" id="counter">0 / 0</div>
      </header>
      <canvas id="canvas" width="900" height="520"></canvas>
      <div class="toolbar">
        <div class="labels" id="labelButtons"></div>
        <div class="nav">
          <button class="ghost" id="prev">Prev</button>
          <button class="ghost" id="next">Next</button>
          <button class="bad" id="discard">Bad sample</button>
        </div>
      </div>
    </section>
    <aside class="side">
      <div class="side-head">
        <h1>Sample</h1>
        <button class="ghost" id="retrain">Rebuild Template Pack</button>
      </div>
      <div class="status" id="retrainStatus"></div>
      <div class="kv" id="meta"></div>
      <div class="prediction" id="primary"></div>
      <div>
        <span class="pill">1 Incendio</span>
        <span class="pill">2 Circle</span>
        <span class="pill">3 Glacius</span>
        <span class="pill">4 Lumos</span>
        <span class="pill">5 Overload</span>
        <span class="pill">X Bad</span>
      </div>
    </aside>
  </main>
  <script>
    const labels = ["incendio", "circle", "glacius", "lumos", "overload"];
    let samples = [];
    let index = 0;
    const canvas = document.getElementById("canvas");
    const ctx = canvas.getContext("2d");

    function fmt(value) {
      if (value === null || value === undefined || value === "") return "-";
      if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
      return String(value);
    }

    function current() { return samples[index] || null; }

    function draw() {
      const sample = current();
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#111318";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      if (!sample || !sample.points || sample.points.length < 2) return;

      const xs = sample.points.map(p => p[0]);
      const ys = sample.points.map(p => p[1]);
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const minY = Math.min(...ys), maxY = Math.max(...ys);
      const pad = 56;
      const spanX = Math.max(1, maxX - minX);
      const spanY = Math.max(1, maxY - minY);
      const scale = Math.min((canvas.width - pad * 2) / spanX, (canvas.height - pad * 2) / spanY);
      const ox = (canvas.width - spanX * scale) / 2 - minX * scale;
      const oy = (canvas.height - spanY * scale) / 2 - minY * scale;
      const map = p => [p[0] * scale + ox, p[1] * scale + oy];

      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      for (let i = 1; i < sample.points.length; i++) {
        const [ax, ay] = map(sample.points[i - 1]);
        const [bx, by] = map(sample.points[i]);
        const t = i / Math.max(1, sample.points.length - 1);
        ctx.strokeStyle = `rgb(${Math.round(80 + 120 * t)}, ${Math.round(170 + 60 * t)}, 255)`;
        ctx.lineWidth = 2 + 4 * t;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.stroke();
      }

      const [sx, sy] = map(sample.points[0]);
      const [ex, ey] = map(sample.points[sample.points.length - 1]);
      ctx.fillStyle = "#80d982";
      ctx.beginPath();
      ctx.arc(sx, sy, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#ff7373";
      ctx.beginPath();
      ctx.arc(ex, ey, 9, 0, Math.PI * 2);
      ctx.fill();
    }

    function renderInfo() {
      const sample = current();
      document.getElementById("counter").textContent =
        samples.length ? `${index + 1} / ${samples.length}` : "0 / 0";
      if (!sample) {
        document.getElementById("meta").innerHTML = "";
        document.getElementById("primary").innerHTML = "";
        return;
      }
      const meta = document.getElementById("meta");
      meta.innerHTML = [
        ["ID", sample.sample_id],
        ["mode", sample.mode],
        ["side", sample.side],
        ["path", sample.path_length],
        ["suggested", sample.suggested_label],
        ["cast", sample.cast_success ? "success" : "no"],
        ["source", sample.source_file],
      ].map(([k, v]) => `<div>${k}</div><div>${fmt(v)}</div>`).join("");
      const primary = sample.primary || {};
      document.getElementById("primary").innerHTML =
        `<strong>Primary</strong>${fmt(primary.spell)} ${fmt(primary.confidence)}<br><span class="muted">${fmt(primary.method)} ${fmt(primary.reason)}</span>`;
    }

    function buttonClasses(base, isSelected) {
      return isSelected ? `${base} selected` : base;
    }

    function renderButtons() {
      const sample = current();
      const pendingLabel = sample ? sample.pending_label : null;
      const pendingStatus = sample ? sample.pending_review_status : null;
      document.querySelectorAll("#labelButtons button[data-label]").forEach(button => {
        button.className = buttonClasses(
          "primary",
          pendingStatus === "accepted" && pendingLabel === button.dataset.label
        );
      });
      document.getElementById("discard").className =
        buttonClasses("bad", pendingStatus === "discarded");
    }

    function render() {
      draw();
      renderInfo();
      renderButtons();
    }

    async function review(label, status = "accepted") {
      const sample = current();
      if (!sample) return;
      const res = await fetch("/api/review", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({sample_id: sample.sample_id, label, review_status: status})
      });
      if (!res.ok) {
        alert(await res.text());
        return;
      }
      const payload = await res.json();
      if (payload.duplicate) {
        await loadSamples();
        return;
      }
      sample.pending_label = status === "accepted" ? label : null;
      sample.pending_review_status = status;
      next();
    }

    function next() {
      if (!samples.length) return;
      index = Math.min(samples.length - 1, index + 1);
      render();
    }

    function prev() {
      if (!samples.length) return;
      index = Math.max(0, index - 1);
      render();
    }

    function installButtons() {
      const root = document.getElementById("labelButtons");
      root.innerHTML = "";
      labels.forEach((label, i) => {
        const button = document.createElement("button");
        button.className = "primary";
        button.dataset.label = label;
        button.textContent = `${i + 1} ${label}`;
        button.onclick = () => review(label, "accepted");
        root.appendChild(button);
      });
      document.getElementById("discard").onclick = () => review(null, "discarded");
      document.getElementById("retrain").onclick = retrain;
      document.getElementById("next").onclick = next;
      document.getElementById("prev").onclick = prev;
      window.addEventListener("keydown", event => {
        if (event.key >= "1" && event.key <= "5") review(labels[Number(event.key) - 1], "accepted");
        if (event.key === "x" || event.key === "X") review(null, "discarded");
        if (event.key === "ArrowRight" || event.key === "d" || event.key === "D") next();
        if (event.key === "ArrowLeft" || event.key === "a" || event.key === "A") prev();
      });
    }

    async function retrain() {
      const button = document.getElementById("retrain");
      const status = document.getElementById("retrainStatus");
      button.disabled = true;
      status.textContent = "Training...";
      try {
        const res = await fetch("/api/retrain", {method: "POST"});
        const payload = await res.json();
        status.textContent = payload.ok
          ? `Template model updated (${payload.committed_reviews || 0} committed)`
          : "Template pack rebuild failed";
        if (payload.ok) await loadSamples();
        if (!payload.ok) alert(payload.output || "Template pack rebuild failed");
      } catch (error) {
        status.textContent = "Template pack rebuild failed";
        alert(String(error));
      } finally {
        button.disabled = false;
      }
    }

    async function loadSamples() {
      const res = await fetch("/api/samples");
      const payload = await res.json();
      samples = payload.samples || [];
      if (index >= samples.length) index = Math.max(0, samples.length - 1);
      render();
    }

    async function boot() {
      installButtons();
      await loadSamples();
    }
    boot();
  </script>
</body>
</html>
"""


def make_handler(samples, output_path, retrain_func=None):
    samples_by_id = {str(sample["sample_id"]): sample for sample in samples}
    committed_ids = load_reviewed_sample_ids(output_path)
    pending_reviews = {}
    trainer = run_retrain if retrain_func is None else retrain_func

    class ReviewHandler(BaseHTTPRequestHandler):
        def _send_json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text, status=200, content_type="text/plain; charset=utf-8"):
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send_text(HTML, content_type="text/html; charset=utf-8")
            elif path == "/api/samples":
                committed_ids.update(load_reviewed_sample_ids(output_path))
                self._send_json({
                    "samples": visible_review_samples(samples, output_path, committed_ids, pending_reviews),
                })
            else:
                self._send_json({"error": "not found"}, status=404)

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/retrain":
                try:
                    records = commit_pending_reviews(output_path, samples_by_id, pending_reviews)
                    pending_reviews.clear()
                    committed_ids.update(str(record.get("sample_id")) for record in records if record.get("sample_id"))
                    result = dict(trainer())
                    result["committed_reviews"] = len(records)
                except Exception as exc:
                    result = {
                        "ok": False,
                        "exit_code": 1,
                        "output": f"Template pack rebuild failed: {exc}",
                        "committed_reviews": 0,
                    }
                self._send_json(result, status=200 if result["ok"] else 500)
                return
            if path != "/api/review":
                self._send_json({"error": "not found"}, status=404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                sample_id = str(payload.get("sample_id"))
                committed_ids.update(load_reviewed_sample_ids(output_path))
                if sample_id in committed_ids:
                    self._send_json({"ok": True, "duplicate": True})
                    return
                if sample_id not in samples_by_id:
                    raise ValueError(f"unknown sample id: {sample_id}")
                review_status = payload.get("review_status", "accepted")
                label = payload.get("label")
                _validate_review_decision(label, review_status)
                pending_reviews[sample_id] = {
                    "label": label if review_status == "accepted" else None,
                    "review_status": review_status,
                }
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json({
                "ok": True,
                "pending": True,
                "sample_id": sample_id,
                "label": pending_reviews[sample_id]["label"],
                "review_status": pending_reviews[sample_id]["review_status"],
            })

        def log_message(self, fmt, *args):
            return

    return ReviewHandler


def _expand_logs(pattern):
    matches = sorted(glob.glob(str(pattern)))
    if matches:
        return [Path(match) for match in matches]
    path = Path(pattern)
    return [path] if path.exists() else []


def serve(samples, output_path, host="127.0.0.1", port=8765, open_browser=True):
    handler = make_handler(samples, output_path)
    last_error = None
    for candidate_port in range(int(port), int(port) + 20):
        try:
            server = ThreadingHTTPServer((host, candidate_port), handler)
            url = f"http://{host}:{candidate_port}"
            print(f"Gesture review: {len(samples)} samples")
            print(f"Writing reviews to {output_path}")
            print(f"Open {url}")
            if open_browser:
                webbrowser.open(url)
            server.serve_forever()
            return 0
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"could not bind review server near port {port}: {last_error}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", default=DEFAULT_LOG_GLOB)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--min-path-length", type=float, default=55.0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    log_paths = _expand_logs(args.logs)
    output_path = Path(args.output)
    samples = load_review_candidates(log_paths, min_path_length=args.min_path_length)
    samples = filter_unreviewed_candidates(samples, output_path)
    return serve(
        samples,
        output_path,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    raise SystemExit(main())
