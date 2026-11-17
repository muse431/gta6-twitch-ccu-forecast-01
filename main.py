"""Hour-by-hour Twitch viewer forecast for a big game launch day.

Written for make.fun's gta6-twitch-ccu-forecast-01: given one case file
(a launch's UTC release day, with hour 1's viewer count already known and a
set of past launches' hourly curves as comparables), forecast the five
quantiles (5/25/50/75/95%) of concurrent Twitch viewers for hours 2..24.

The model, in one paragraph: launches that unlocked at midnight local time,
rolling around the world like Grand Theft Auto VI does, share a release-day
shape, but the shape scales sublinearly with the size of hour 1 -- a launch
whose first hour is already huge has most of its audience from the start,
while a small first hour can ramp tenfold into prime time (across the
comparables, log peak/hour-1 correlates about -0.94 with log hour-1). So for
each hour h this program regresses, over the midnight-local comparables,
log viewers at h on log viewers at hour 1, and takes the forecast quantiles
as the fitted line at the case's own hour-1 count plus the empirical
quantiles of the regression residuals. Everything is a deterministic
function of the case file: no randomness, no clock, no network.

Run it the way the grader does (one case in the input directory):
    MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The five quantile levels every forecast row carries, in order.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard-normal quantiles at those levels, for the fallback forecast.
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
# A comparable counts only if almost its whole release day is present.
MIN_DAY_HOURS = 20
# The midnight-local pool is trusted on its own once it has this many curves.
MIN_POOL = 8


def parse_ts(ts):
    """Parse the case files' ISO-8601 UTC timestamps."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def day_curve(comparable):
    """A comparable's release-day viewers by hour (1..24), or None.

    The comparable's hourly points are aligned to its own day_start; a point
    counts for hour h when it starts within a minute of day_start + (h - 1)
    hours. The curve is usable when at least MIN_DAY_HOURS of the day's hours
    are present and hour 1 drew a positive count.
    """
    start = parse_ts(comparable["day_start"])
    curve = {}
    for point in comparable.get("hourly", []):
        offset = (parse_ts(point["from"]) - start).total_seconds() / 3600.0
        hour = int(round(offset)) + 1
        if abs(offset - round(offset)) < 0.02 and 1 <= hour <= 24:
            curve[hour] = point["viewers"]
    if len(curve) < MIN_DAY_HOURS or not curve.get(1):
        return None
    return curve


def quantile(sorted_values, tau):
    """The tau quantile of sorted values, linearly interpolated."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    pos = tau * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def fit_line(points):
    """Least squares (intercept, slope) for (x, y) points; slope 1 if flat."""
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    if sxx <= 0:
        return mean_y - mean_x, 1.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sxx
    return mean_y - slope * mean_x, slope


def fallback_quantiles(p1, hour):
    """The house baseline's shape, used only where a hour has no data."""
    spread = 0.15 * math.sqrt(hour - 1)
    return [p1 * math.exp(z * spread) for z in Z]


def forecast_case(case):
    """Build the {"hours": [...]} forecast for one parsed case."""
    first = next((k for k in case.get("known", []) if k.get("hour") == 1), None)
    p1 = max(1.0, float(first["viewers"])) if first else 1.0
    log_p1 = math.log(p1)

    curves = []
    midnight_curves = []
    for comparable in case.get("comparables", []):
        curve = day_curve(comparable)
        if curve is None:
            continue
        curves.append(curve)
        unlock = str(comparable.get("unlock", "")).lower()
        if "midnight" in unlock:
            midnight_curves.append(curve)
    pool = midnight_curves if len(midnight_curves) >= MIN_POOL else curves

    rows = []
    for target in case.get("forecast", []):
        hour = target["hour"]
        points = [
            (math.log(curve[1]), math.log(curve[hour]))
            for curve in pool
            if curve.get(hour)
        ]
        if len(points) >= 3:
            intercept, slope = fit_line(points)
            residuals = sorted(
                y - (intercept + slope * x) for x, y in points
            )
            centre = intercept + slope * log_p1
            qs = [math.exp(centre + quantile(residuals, tau)) for tau in LEVELS]
        else:
            qs = fallback_quantiles(p1, hour)
        # Keep every quantile a finite, in-range, non-decreasing count.
        cleaned = []
        for value in qs:
            value = min(max(value, 0.01), 1_000_000_000.0)
            if cleaned and value < cleaned[-1]:
                value = cleaned[-1]
            cleaned.append(value)
        rows.append({"hour": hour, "q": cleaned})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
