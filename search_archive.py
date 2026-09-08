"""
search_archive.py — Search LiveATC archives for a flight over a time window.

Given a date and time range, this downloads each 30-minute archive block from
archive.liveatc.net, transcribes it with Whisper, searches for the callsign
(e.g. "Sky Flite two zero three"), and writes the results to docs/index.html
so GitHub Pages can display them.

Normally run by the GitHub Actions workflow, but works locally too:

    python search_archive.py --date 2026-09-08 --start 14:00 --end 16:00 \
        --tz eastern --flight 203 --telephony "sky flite"
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

# ---------------------------------------------------------------------------
# Callsign matching
# ---------------------------------------------------------------------------
DIGIT_WORDS = {
    "0": ["zero", "oh", "o", "0"],
    "1": ["one", "won", "1"],
    "2": ["two", "to", "too", "2"],
    "
