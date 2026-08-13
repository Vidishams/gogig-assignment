"""
Aggregates individual check results into one overall recommendation.

This is the "structure the uncertainty" layer the assignment asks for:
instead of making a human read 6 separate pass/fail rows, we combine them
into accept / needs_review / reject with a reason, weighted by how
critical each check is and how confident it was.
"""

# Checks that, on their own, are serious enough to reject outright when
# failed with high confidence (i.e. likely fraud/invalid submission,
# not just poor photo quality).
CRITICAL_CHECKS = {"tamper", "duplicate"}

HIGH_CONFIDENCE = 0.6
LOW_CONFIDENCE = 0.35


def compute_verdict(check_results: list[dict]) -> dict:
    """check_results: list of {"check_name", "passed", "confidence", ...}"""
    if not check_results:
        return {"recommendation": "needs_review", "reasoning": "No checks completed."}

    failed = [r for r in check_results if not r["passed"]]

    critical_high_conf_failures = [
        r for r in failed
        if r["check_name"] in CRITICAL_CHECKS and r["confidence"] >= HIGH_CONFIDENCE
    ]
    if critical_high_conf_failures:
        names = ", ".join(r["check_name"] for r in critical_high_conf_failures)
        return {
            "recommendation": "reject",
            "reasoning": f"High-confidence failure on critical check(s): {names}.",
        }

    borderline = [r for r in failed if r["confidence"] < LOW_CONFIDENCE]
    non_critical_failures = [r for r in failed if r["check_name"] not in CRITICAL_CHECKS]

    if not failed:
        return {"recommendation": "accept", "reasoning": "All checks passed."}

    if borderline or non_critical_failures:
        names = ", ".join(r["check_name"] for r in failed)
        return {
            "recommendation": "needs_review",
            "reasoning": f"Failed check(s) with non-critical or low-confidence signal: {names}. "
                          f"Recommend human review rather than auto-reject.",
        }

    names = ", ".join(r["check_name"] for r in failed)
    return {
        "recommendation": "needs_review",
        "reasoning": f"Failed check(s): {names}.",
    }
