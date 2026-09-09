"""
search_archive.py — Search LiveATC archives for a flight over a time window.
"""

import argparse
import datetime as dt
import html
import re
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/129.0.0.0 Safari/537.36"),
    "Referer": "https://www.liveatc.net/",
    "Accept": "*/*",
}

DIGIT_WORDS = {
    "0": ["zero", "oh", "o", "0"],
    "1": ["one", "won", "1"],
    "2": ["two", "to", "too", "2"],
    "3": ["three", "tree", "3"],
    "4": ["four", "fower", "for", "4"],
    "5": ["five", "fife", "5"],
    "6": ["six", "6"],
    "7": ["seven", "7"],
    "8": ["eight", "ate", "8"],
    "9": ["nine", "niner", "9"],
}

WORD_ALIASES = {
    "flite": ["flite", "flight", "flyte"],
    "sky": ["sky", "skye"],
}


def build_digits_pattern(flight_number: str) -> str:
    spoken = r"[\s\-]*".join(
        f"(?:{'|'.join(DIGIT_WORDS[d])})" for d in flight_number
    )
    return f"(?:{spoken}|{re.escape(flight_number)})"


def build_callsign_pattern(telephony: str) -> str:
    return r"[\s\-]*".join(
        f"(?:{'|'.join(WORD_ALIASES.get(w, [w]))})"
        for w in telephony.lower().split()
    )


def normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def block_times(start_utc, end_utc):
    minute = 0 if start_utc.minute < 30 else 30
    t = start_utc.replace(minute=minute, second=0, microsecond=0)
    while t < end_utc:
        yield t
        t += dt.timedelta(minutes=30)


def block_url(pattern: str, t) -> str:
    return (pattern
            .replace("{mon}", t.strftime("%b"))
            .replace("{dd}", t.strftime("%d"))
            .replace("{yyyy}", t.strftime("%Y"))
            .replace("{hhmm}", t.strftime("%H%M")))


def download(url: str, dest: Path) -> str:
    try:
        with requests.get(url, stream=True, timeout=60,
                          headers=BROWSER_HEADERS) as r:
            if r.status_code == 404:
                return "missing"
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
        return "ok"
    except requests.RequestException as e:
        print(f"  download failed: {e}")
        return "error"


PAGE_CSS = """
:root {
  --board: #cfd6dc; --ink: #17222b; --dim: #5c6b76;
  --hit: #e4572e; --maybe: #8195a3; --strip: #f8f9fa;
}
* { box-sizing: border-box; margin: 0; }
body {
  background: var(--board); color: var(--ink);
  font-family: "Avenir Next", "Segoe UI", system-ui, sans-serif;
  padding: 24px 16px 64px; max-width: 760px; margin: 0 auto;
}
header { margin-bottom: 28px; }
h1 { font-size: 1.35rem; font-weight: 700; }
.callsign { color: var(--hit); }
.params { color: var(--dim); font-size: .9rem; margin-top: 6px; line-height: 1.5; }
h2 { font-size: .95rem; font-weight: 600; margin: 26px 0 10px; color: var(--dim); }
.strip {
  background: var(--strip); border-left: 6px solid var(--hit);
  padding: 10px 14px; margin-bottom: 8px; border-radius: 2px;
  box-shadow: 0 1px 0 rgba(23,34,43,.18);
}
.strip.maybe { border-left-color: var(--maybe); }
.strip .when {
  font-family: ui-monospace, "SF Mono", Consolas, monospace;
  font-size: .82rem; color: var(--dim); margin-bottom: 4px;
}
.strip .heard { font-size: .95rem; line-height: 1.45; }
.empty { color: var(--dim); font-style: italic; padding: 8px 0; }
.blocks { font-size: .85rem; color: var(--dim); line-height: 1.7; }
.blocks a { color: var(--ink); }
footer { margin-top: 40px; font-size: .8rem; color: var(--dim); }
"""


def render_page(params, matches, possibles, blocks_report):
    def strip_html(m, cls=""):
        t_utc, text = m
        t_loc = t_utc.astimezone(EASTERN)
        return (
            f'<div class="strip {cls}">'
            f'<div class="when">{t_loc.strftime("%H:%M:%S")} ET '
            f'&nbsp;({t_utc.strftime("%H:%M:%S")}Z)</div>'
            f'<div class="heard">{html.escape(text.strip())}</div></div>'
        )

    match_html = "".join(strip_html(m) for m in matches) or \
        '<p class="empty">No confirmed mentions in this window.</p>'
    maybe_html = "".join(strip_html(m, "maybe") for m in possibles) or \
        '<p class="empty">None.</p>'

    blocks_html = "<br>".join(
        f'{label} — {status}' + (f' — <a href="{link}">transcript</a>' if link else "")
        for label, status, link in blocks_report
    )

    generated = dt.datetime.now(UTC).astimezone(EASTERN).strftime("%b %d, %Y %H:%M ET")

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ATC search — {html.escape(params['callsign'])}</title>
<style>{PAGE_CSS}</style>
</head><body>
<header>
  <h1>Heard on frequency: <span class="callsign">{html.escape(params['callsign'])}</span></h1>
  <div class="params">{html.escape(params['window'])}<br>
  Feed pattern: {html.escape(params['pattern'])}</div>
</header>
<h2>Confirmed mentions</h2>
{match_html}
<h2>Possible mentions (callsign or number heard alone)</h2>
{maybe_html}
<h2>Archive blocks searched</h2>
<p class="blocks">{blocks_html}</p>
<footer>Generated {generated}. Audio &copy; LiveATC.net — for personal use.</footer>
</body></html>
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--tz", default="eastern", choices=["eastern", "utc"])
    p.add_argument("--flight", default="203")
    p.add_argument("--telephony", default="sky flite")
    p.add_argument("--model", default="small")
    p.add_argument("--pattern", required=True)
    args = p.parse_args()

    if not args.flight.isdigit():
        sys.exit("Flight number should be digits only (e.g. 203).")

    tz = EASTERN if args.tz == "eastern" else UTC
    d = dt.date.fromisoformat(args.date)
    t0 = dt.time.fromisoformat(args.start)
    t1 = dt.time.fromisoformat(args.end)
    start_utc = dt.datetime.combine(d, t0, tz).astimezone(UTC)
    end_utc = dt.datetime.combine(d, t1, tz).astimezone(UTC)
    if end_utc <= start_utc:
        sys.exit("End time must be after start time.")

    callsign_re = re.compile(build_callsign_pattern(args.telephony))
    digits_re = re.compile(build_digits_pattern(args.flight))
    full_re = re.compile(build_callsign_pattern(args.telephony)
                         + r"(?:\s+\w+){0,3}?\s+"
                         + build_digits_pattern(args.flight))

    print(f"Window (UTC): {start_utc:%Y-%m-%d %H:%M} to {end_utc:%H:%M}Z")
    print(f"Loading Whisper model '{args.model}'...")
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    docs = Path("docs")
    tdir = docs / "transcripts"
    tdir.mkdir(parents=True, exist_ok=True)

    matches, possibles, blocks_report = [], [], []

    for t in block_times(start_utc, end_utc):
        url = block_url(args.pattern, t)
        label = t.astimezone(EASTERN).strftime("%H:%M ET") + f" ({t:%H%M}Z)"
        print(f"\n=== Block {label}: {url}")

        tmp = Path(tempfile.gettempdir()) / "block.mp3"
        status = download(url, tmp)
        if status == "missing":
            print("  no archive for this block (404)")
            blocks_report.append((label, "no archive found", None))
            continue
        if status == "error":
            blocks_report.append((label, "download failed", None))
            continue

        print("  transcribing...")
        try:
            segments, _ = model.transcribe(
                str(tmp), language="en", beam_size=5, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500})
            segments = list(segments)
        except Exception as e:
            print(f"  transcription failed: {e}")
            blocks_report.append((label, "transcription failed", None))
            continue

        tname = t.strftime("%Y%m%d-%H%MZ") + ".txt"
        with open(tdir / tname, "w", encoding="utf-8") as f:
            for seg in segments:
                abs_t = (t + dt.timedelta(seconds=seg.start)).astimezone(EASTERN)
                f.write(f"[{abs_t:%H:%M:%S} ET] {seg.text.strip()}\n")

        hit_count = 0
        for seg in segments:
            clean = normalize(seg.text)
            abs_t = t + dt.timedelta(seconds=seg.start)
            if full_re.search(clean):
                matches.append((abs_t, seg.text))
                hit_count += 1
            elif digits_re.search(clean) or callsign_re.search(clean):
                possibles.append((abs_t, seg.text))

        print(f"  {hit_count} confirmed match(es) in this block")
        blocks_report.append((label, f"searched, {hit_count} match(es)",
                              f"transcripts/{tname}"))

    callsign = f"{args.telephony.title()} {args.flight}"
    window = (f"{d:%A, %B %d, %Y}, {args.start}\u2013{args.end} "
              f"{'Eastern' if args.tz == 'eastern' else 'UTC'}")
    page = render_page(
        {"callsign": callsign, "window": window, "pattern": args.pattern},
        matches, possibles, blocks_report)
    (docs / "index.html").write_text(page, encoding="utf-8")

    print(f"\nDone: {len(matches)} confirmed, {len(possibles)} possible. "
          f"Results written to docs/index.html")


if __name__ == "__main__":
    main()
