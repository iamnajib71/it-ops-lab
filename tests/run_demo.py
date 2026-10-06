"""Send a set of realistic tickets through the copilot and check each lands in the expected queue.

Usage:  python tests/run_demo.py          (n8n must be running with the workflows published)
"""
import json
import sys
import time
import urllib.request

URL = "http://localhost:5678/webhook/ticket"

CASES = [
    # (expected statuses, ticket)
    ({"auto_resolved", "awaiting_approval"}, {"name": "Priya Shah", "subject": "Printing from home",
        "body": "How do I print to the office printer when I'm working from home?"}),
    ({"auto_resolved", "awaiting_approval"}, {"name": "Tom Nguyen", "subject": "Where is the Finance share?",
        "body": "Which drive letter or path do I use to open the Finance folder from my laptop?"}),
    ({"escalated"}, {"name": "Ava Brown", "subject": "Clicked a link in a weird email",
        "body": "I clicked a link in an email saying my mailbox was full and typed my password. Now I'm worried."}),
    ({"awaiting_approval"}, {"name": "Liam Chen", "subject": "Need access to Finance share",
        "body": "I've moved to the finance team. Can I get access to the Finance share please?"}),
    ({"awaiting_approval", "escalated"}, {"name": "Mia Patel", "subject": "Nobody can print",
        "body": "The whole office can't print since this morning, jobs just sit in the queue."}),
    ({"awaiting_approval"}, {"name": "Noah Wilson", "subject": "Payroll login",
        "body": "My password is Summer2026! and it stopped working on the payroll site, my TFN is 123 456 789."}),
]


def post(ticket):
    req = urllib.request.Request(URL, json.dumps(ticket).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main():
    passed = 0
    for expected, t in CASES:
        start = time.time()
        r = post(t)
        ok = r.get("status") in expected
        passed += ok
        v = r.get("judge_verdict") or {}
        print(f"[{'PASS' if ok else 'FAIL'}] #{r.get('id')} {t['subject']!r}: {r.get('priority')} {r.get('category')} -> "
              f"{r.get('status')} (expected {'/'.join(sorted(expected))}), confidence {r.get('confidence')}, "
              f"{time.time() - start:.1f}s")
        if v.get("gate_reasons"):
            print("       held because:", "; ".join(v["gate_reasons"]))
    print(f"\n{passed}/{len(CASES)} tickets routed as expected")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
