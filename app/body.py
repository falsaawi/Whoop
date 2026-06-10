"""Human "buddy" body map: organs linked to ICD-10 codes and profiled from
the wearable signals Whoop provides.

The idea: take the metrics the existing insights engine already derives
(resting heart rate, HRV, SpO2, respiratory rate, skin temperature, sleep,
recovery, training strain) and project them onto the organ / body-system
they speak to.  Each organ carries a curated set of **ICD-10 codes** for the
conditions that those signals can hint at, and a small rule set decides
whether the organ looks ``ok``, deserves a ``watch``, or warrants an
``alert`` — flagging the specific ICD-10 codes a clinician might consider.

Nothing here is a diagnosis.  A consumer wearable cannot diagnose disease;
it surfaces deviations from *your own* baseline.  The ICD-10 links exist so
the profile speaks a standard clinical vocabulary, not to label the user.

``compute_body_profile`` is the entry point.  ``_assess`` is pure (takes the
insights dict, returns JSON-able output) so it can be unit-tested without a
database.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.insights import compute_insights

# --------------------------------------------------------------------------- #
# Status levels (ordered worst-first for sorting/aggregation)
# --------------------------------------------------------------------------- #
ALERT, WATCH, OK, UNMONITORED = "alert", "watch", "ok", "unmonitored"
_RANK = {ALERT: 0, WATCH: 1, OK: 2, UNMONITORED: 3}


def _icd(code: str, name: str) -> dict:
    return {"code": code, "name": name}


# --------------------------------------------------------------------------- #
# Organ catalogue
# --------------------------------------------------------------------------- #
# Each organ:
#   id, name, system               – identity
#   x, y                           – position on the 200x420 SVG body figure
#   metrics                        – Whoop signals that inform it (for display)
#   icd10                          – curated reference codes for this organ
#   assess(ctx)                    – rule fn -> (status, summary, [flagged codes])
#
# The ``ctx`` passed to each assess fn bundles the pieces of the insights dict
# the rules need, so the rules stay short and readable.
# --------------------------------------------------------------------------- #
def _heart(ctx) -> tuple[str, str, list[str]]:
    rhr_pct = ctx["trends"].get("rhr_pct")
    hrv_pct = ctx["trends"].get("hrv_pct")
    flags: list[str] = []
    status = OK
    notes: list[str] = []

    if rhr_pct is not None and rhr_pct >= 10:
        status = ALERT
        flags += ["R00.0", "I10"]
        notes.append(f"resting HR {rhr_pct:.0f}% above your baseline")
    elif rhr_pct is not None and rhr_pct >= 5:
        status = WATCH
        flags.append("R00.0")
        notes.append(f"resting HR {rhr_pct:.0f}% above baseline")

    if hrv_pct is not None and hrv_pct <= -15:
        status = ALERT
        flags += ["R00.2", "I49.9"]
        notes.append(f"HRV {abs(hrv_pct):.0f}% below baseline")
    elif hrv_pct is not None and hrv_pct <= -10:
        status = max_status(status, WATCH)
        flags.append("R00.2")
        notes.append(f"HRV {abs(hrv_pct):.0f}% below baseline")

    if status == OK:
        summary = "Heart-rate and HRV are tracking your normal range."
    else:
        summary = "Cardiac strain signals: " + "; ".join(notes) + "."
    return status, summary, _dedupe(flags)


def _lungs(ctx) -> tuple[str, str, list[str]]:
    spo2 = ctx["averages"].get("spo2_percentage")
    resp_pct = ctx["trends"].get("respiratory_pct")
    flags: list[str] = []
    status = OK
    notes: list[str] = []

    if spo2 is not None and spo2 < 92:
        status = ALERT
        flags += ["R09.02", "J96.90"]
        notes.append(f"average SpO2 {spo2:.1f}% (low)")
    elif spo2 is not None and spo2 < 95:
        status = WATCH
        flags.append("R09.02")
        notes.append(f"average SpO2 {spo2:.1f}%")

    if resp_pct is not None and resp_pct >= 10:
        status = ALERT
        flags += ["R06.89", "R06.00"]
        notes.append(f"respiratory rate {resp_pct:.0f}% above baseline")
    elif resp_pct is not None and resp_pct >= 6:
        status = max_status(status, WATCH)
        flags.append("R06.89")
        notes.append(f"respiratory rate {resp_pct:.0f}% above baseline")

    if status == OK:
        summary = "Blood oxygen and breathing rate look normal."
    else:
        summary = "Respiratory signals: " + "; ".join(notes) + "."
    return status, summary, _dedupe(flags)


def _brain(ctx) -> tuple[str, str, list[str]]:
    sleep = ctx["sleep_analysis"]
    avg_h = sleep.get("avg_hours")
    bed_std = sleep.get("bedtime_std_hours")
    perf = sleep.get("avg_performance")
    flags: list[str] = []
    status = OK
    notes: list[str] = []

    if avg_h is not None and avg_h < 6:
        status = ALERT
        flags += ["G47.00", "F51.01"]
        notes.append(f"averaging {avg_h:.1f}h sleep")
    elif avg_h is not None and avg_h < 7:
        status = WATCH
        flags.append("G47.00")
        notes.append(f"averaging {avg_h:.1f}h sleep")

    if bed_std is not None and bed_std > 1.5:
        status = max_status(status, WATCH)
        flags.append("G47.9")
        notes.append(f"bedtime varies ±{bed_std:.1f}h")

    if perf is not None and perf < 70:
        status = max_status(status, WATCH)
        flags.append("G47.9")
        notes.append(f"sleep performance {perf:.0f}%")

    if status == OK:
        summary = "Sleep duration, quality and timing support good rest."
    else:
        summary = "Sleep / circadian signals: " + "; ".join(notes) + "."
    return status, summary, _dedupe(flags)


def _airway(ctx) -> tuple[str, str, list[str]]:
    """Upper airway — apnea risk hinted by SpO2 dips alongside disturbed sleep."""
    spo2 = ctx["averages"].get("spo2_percentage")
    perf = ctx["sleep_analysis"].get("avg_performance")
    resp = ctx["sleep_analysis"].get("avg_respiratory_rate")
    flags: list[str] = []
    status = OK
    notes: list[str] = []

    if spo2 is not None and spo2 < 94 and perf is not None and perf < 80:
        status = WATCH
        flags += ["G47.33"]
        notes.append(f"SpO2 {spo2:.1f}% with sleep performance {perf:.0f}%")

    if status == OK:
        summary = "No combined oxygen/sleep pattern suggesting apnea."
    else:
        summary = "Possible sleep-disordered breathing: " + "; ".join(notes) + "."
    if resp is not None:
        summary += f" (avg respiratory rate {resp:.1f}/min)"
    return status, summary, _dedupe(flags)


def _muscles(ctx) -> tuple[str, str, list[str]]:
    training = ctx["training_analysis"]
    overreach = training.get("overreach_days_14d", 0)
    wpw = training.get("workouts_per_week")
    flags: list[str] = []
    status = OK
    notes: list[str] = []

    if overreach >= 3:
        status = ALERT
        flags += ["T73.3", "M79.1"]
        notes.append(f"{overreach} hard sessions on low-recovery days (14d)")
    elif overreach >= 2:
        status = WATCH
        flags.append("M79.1")
        notes.append(f"{overreach} overreaching days in the last 2 weeks")

    if wpw is not None and wpw < 1.5:
        status = max_status(status, WATCH)
        flags.append("M62.81")
        notes.append(f"only {wpw:.1f} workouts/week")

    if status == OK:
        summary = "Training load is matched to recovery."
    else:
        summary = "Musculoskeletal load signals: " + "; ".join(notes) + "."
    return status, summary, _dedupe(flags)


def _immune(ctx) -> tuple[str, str, list[str]]:
    """Whole-body illness signal: elevated skin temp + respiratory rate + RHR
    moving together is Whoop's classic 'getting sick' fingerprint."""
    cur = ctx["current"]
    trends = ctx["trends"]
    skin = cur.get("skin_temp")
    skin_avg = ctx["averages"].get("skin_temp_celsius")
    resp_pct = trends.get("respiratory_pct")
    rhr_pct = trends.get("rhr_pct")
    flags: list[str] = []
    status = OK
    notes: list[str] = []

    elevated = 0
    if skin is not None and skin_avg is not None and skin - skin_avg >= 0.5:
        elevated += 1
        notes.append(f"skin temp +{skin - skin_avg:.1f}°C vs avg")
    if resp_pct is not None and resp_pct >= 6:
        elevated += 1
        notes.append(f"respiratory rate +{resp_pct:.0f}%")
    if rhr_pct is not None and rhr_pct >= 5:
        elevated += 1
        notes.append(f"resting HR +{rhr_pct:.0f}%")

    if elevated >= 2:
        status = ALERT
        flags += ["R50.9", "R53.83"]
    elif elevated == 1:
        status = WATCH
        flags.append("R53.83")

    if status == OK:
        summary = "No combined fever / illness pattern in your vitals."
    else:
        summary = "Possible immune stress: " + "; ".join(notes) + "."
    return status, summary, _dedupe(flags)


def _skin(ctx) -> tuple[str, str, list[str]]:
    cur = ctx["current"]
    skin = cur.get("skin_temp")
    skin_avg = ctx["averages"].get("skin_temp_celsius")
    flags: list[str] = []
    status = OK
    notes: list[str] = []
    if skin is not None and skin_avg is not None:
        delta = skin - skin_avg
        if delta >= 0.8:
            status = WATCH
            flags.append("R50.9")
            notes.append(f"skin temperature {delta:+.1f}°C vs your average")
    if status == OK:
        summary = "Skin temperature is within your normal range."
    else:
        summary = "Thermoregulation: " + "; ".join(notes) + "."
    return status, summary, _dedupe(flags)


def _unmonitored(reason: str):
    def fn(_ctx) -> tuple[str, str, list[str]]:
        return UNMONITORED, reason, []
    return fn


ORGANS: list[dict] = [
    {
        "id": "brain", "name": "Brain", "system": "Nervous / Sleep",
        "x": 120, "y": 42,
        "metrics": ["Sleep duration", "Sleep performance", "Sleep consistency"],
        "icd10": [
            _icd("G47.00", "Insomnia, unspecified"),
            _icd("G47.9", "Sleep disorder, unspecified"),
            _icd("F51.01", "Primary insomnia"),
            _icd("R53.83", "Other fatigue"),
        ],
        "assess": _brain,
    },
    {
        "id": "airway", "name": "Upper airway", "system": "Respiratory / Sleep",
        "x": 120, "y": 96,
        "metrics": ["SpO2", "Respiratory rate", "Sleep performance"],
        "icd10": [
            _icd("G47.33", "Obstructive sleep apnea (adult/pediatric)"),
            _icd("R06.83", "Snoring"),
        ],
        "assess": _airway,
    },
    {
        "id": "lungs", "name": "Lungs", "system": "Respiratory",
        "x": 100, "y": 154,
        "metrics": ["SpO2", "Respiratory rate"],
        "icd10": [
            _icd("R09.02", "Hypoxemia"),
            _icd("R06.00", "Dyspnea, unspecified"),
            _icd("R06.89", "Other abnormalities of breathing"),
            _icd("J96.90", "Respiratory failure, unspecified"),
        ],
        "assess": _lungs,
    },
    {
        "id": "heart", "name": "Heart", "system": "Cardiovascular",
        "x": 140, "y": 158,
        "metrics": ["Resting heart rate", "Heart-rate variability (HRV)", "Recovery"],
        "icd10": [
            _icd("I10", "Essential (primary) hypertension"),
            _icd("R00.0", "Tachycardia, unspecified"),
            _icd("R00.2", "Palpitations"),
            _icd("I49.9", "Cardiac arrhythmia, unspecified"),
            _icd("I48.91", "Atrial fibrillation, unspecified"),
        ],
        "assess": _heart,
    },
    {
        "id": "immune", "name": "Immune system", "system": "Systemic",
        "x": 120, "y": 188,
        "metrics": ["Skin temperature", "Respiratory rate", "Resting heart rate"],
        "icd10": [
            _icd("R50.9", "Fever, unspecified"),
            _icd("R53.83", "Other fatigue"),
            _icd("R68.89", "Other general symptoms and signs"),
        ],
        "assess": _immune,
    },
    {
        "id": "liver", "name": "Liver", "system": "Hepatic / Metabolic",
        "x": 102, "y": 214,
        "metrics": ["Not directly measured by Whoop"],
        "icd10": [
            _icd("K76.0", "Fatty (change of) liver, not elsewhere classified"),
            _icd("R74.0", "Elevated liver enzymes"),
        ],
        "assess": _unmonitored(
            "Not measured by Whoop directly. HRV suppression after alcohol or "
            "late heavy meals is the closest proxy — see the Heart organ."
        ),
    },
    {
        "id": "stomach", "name": "Stomach / Gut", "system": "Digestive",
        "x": 140, "y": 214,
        "metrics": ["Not directly measured by Whoop"],
        "icd10": [
            _icd("K30", "Functional dyspepsia"),
            _icd("K21.9", "Gastro-esophageal reflux disease without esophagitis"),
        ],
        "assess": _unmonitored(
            "Not measured by a wearable. Late meals can show up indirectly as "
            "poorer sleep performance — see the Brain organ."
        ),
    },
    {
        "id": "kidneys", "name": "Kidneys", "system": "Renal / Hydration",
        "x": 120, "y": 242,
        "metrics": ["Not directly measured by Whoop"],
        "icd10": [
            _icd("E86.0", "Dehydration"),
            _icd("N28.9", "Disorder of kidney and ureter, unspecified"),
        ],
        "assess": _unmonitored(
            "Hydration status is not measured directly. Dehydration commonly "
            "lowers HRV and recovery — see the Heart organ."
        ),
    },
    {
        "id": "skin", "name": "Skin", "system": "Integumentary",
        "x": 184, "y": 252,
        "metrics": ["Skin temperature"],
        "icd10": [
            _icd("R50.9", "Fever, unspecified"),
            _icd("R61", "Generalized hyperhidrosis"),
        ],
        "assess": _skin,
    },
    {
        "id": "muscles", "name": "Muscles", "system": "Musculoskeletal",
        "x": 102, "y": 330,
        "metrics": ["Training strain", "Recovery", "Workout frequency"],
        "icd10": [
            _icd("M79.1", "Myalgia"),
            _icd("M62.81", "Muscle weakness (generalized)"),
            _icd("T73.3", "Exhaustion due to excessive exertion"),
        ],
        "assess": _muscles,
    },
]

# Flat lookup of every ICD-10 code we reference, so the API can return the
# human-readable name for any code a rule flags.
ICD10_INDEX: dict[str, str] = {
    item["code"]: item["name"] for organ in ORGANS for item in organ["icd10"]
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def max_status(a: str, b: str) -> str:
    """Return the more severe of two statuses (alert > watch > ok)."""
    return a if _RANK[a] <= _RANK[b] else b


def _dedupe(codes: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for c in codes:
        seen.setdefault(c, None)
    return list(seen)


# --------------------------------------------------------------------------- #
# Core assessment (pure: insights dict -> body profile dict)
# --------------------------------------------------------------------------- #
def _assess(insights: dict) -> dict:
    ctx = {
        "current": insights.get("current", {}),
        "averages": insights.get("averages", {}),
        "trends": insights.get("trends", {}),
        "baselines": insights.get("baselines", {}),
        "sleep_analysis": insights.get("sleep_analysis", {}),
        "training_analysis": insights.get("training_analysis", {}),
    }

    organs_out: list[dict] = []
    counts = {ALERT: 0, WATCH: 0, OK: 0, UNMONITORED: 0}
    for organ in ORGANS:
        status, summary, flagged = organ["assess"](ctx)
        counts[status] += 1
        organs_out.append(
            {
                "id": organ["id"],
                "name": organ["name"],
                "system": organ["system"],
                "x": organ["x"],
                "y": organ["y"],
                "status": status,
                "summary": summary,
                "metrics": organ["metrics"],
                "icd10": organ["icd10"],
                "flagged": [
                    {"code": c, "name": ICD10_INDEX.get(c, c)} for c in flagged
                ],
            }
        )

    organs_out.sort(key=lambda o: _RANK[o["status"]])

    if counts[ALERT]:
        headline = "Some systems need attention"
        level = ALERT
    elif counts[WATCH]:
        headline = "A few systems worth watching"
        level = WATCH
    else:
        headline = "All monitored systems look healthy"
        level = OK

    return {
        "days": insights.get("days"),
        "since": insights.get("since"),
        "generated_at": insights.get("generated_at"),
        "profile": insights.get("profile", {}),
        "overall": {
            "level": level,
            "headline": headline,
            "counts": counts,
        },
        "organs": organs_out,
        "disclaimer": (
            "This is a wellness view built from consumer wearable data, not a "
            "medical diagnosis. ICD-10 codes show which clinical conditions a "
            "signal may relate to — discuss any persistent change with a doctor."
        ),
    }


def compute_body_profile(db: Session, days: int = 90) -> dict:
    """Compute the organ-level health profile for the given window."""
    insights = compute_insights(db, days=days)
    return _assess(insights)
