"""
E2E 验证脚本 - 测试所有 Phase 2 核心 API
用法: python3 tests/e2e_verify.py [port]
"""
import urllib.request
import json
import sys

BASE = f"http://127.0.0.1:{sys.argv[1] if len(sys.argv) > 1 else 8766}"
PASS = "[PASS]"
FAIL = "[FAIL]"

def get(path):
    with urllib.request.urlopen(f"{BASE}{path}") as r:
        return json.loads(r.read())

def post(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}", data=body,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def http(method, path, data=None):
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method=method
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

errors = []

def check(label, condition, detail=""):
    if condition:
        print(f"  {PASS} {label}" + (f" ({detail})" if detail else ""))
    else:
        print(f"  {FAIL} {label}" + (f" ({detail})" if detail else ""))
        errors.append(label)

print("=" * 50)
print(f"E2E Verification - {BASE}")
print("=" * 50)

# 1. Health
print("\n[1] Health Check")
r = get("/api/health")
check("status ok", r.get("status") == "ok", r.get("status"))

# 2. Skills
print("\n[2] Skills API")
resp = get("/api/skills")
# Backend returns {"skills": [...], "total": N}
skills = resp.get("skills", resp) if isinstance(resp, dict) else resp
check("skills loaded", len(skills) > 0, f"{len(skills)} skills")
for s in skills:
    print(f"     - {s['name']} ({s['id']})")

# 3. Skill match
print("\n[3] Agent Match")
r = post("/api/agent/match", {"query": "help review procurement PPT"})
check("match found", r.get("matched"), f"skill={r.get('skill_name')} conf={r.get('confidence')}")

r2 = post("/api/skills/match", {"query": "procurement review"})
# Backend returns {"matches": [...], "total": N}
check("skills/match works", "matches" in r2, f"total={r2.get('total')}")

# 4. Know-how stats
print("\n[4] Know-how Stats")
r = get("/api/knowhow/stats")
# Backend returns {"total_rules": N, "active_rules": N, ...}
check("stats returned", "total_rules" in r,
      f"total={r.get('total_rules')} active={r.get('active_rules')}")

# 5. Know-how list
print("\n[5] Know-how List")
resp5 = get("/api/knowhow")
# Backend returns {"rules": [...]} or plain list
rules = resp5.get("rules", resp5) if isinstance(resp5, dict) else resp5
check("rules returned", isinstance(rules, list), f"{len(rules)} rules")
if rules:
    print(f"     Sample: [{rules[0]['category']}] {rules[0]['rule_text'][:40]}...")

# 6. Knowledge stats
print("\n[6] Knowledge Stats")
r = get("/api/knowledge/stats")
check("stats returned", "total_ppt_imports" in r,
      f"ppt={r.get('total_ppt_imports')} chunks={r.get('total_vector_chunks')}")

# 7. Know-how CRUD
print("\n[7] Know-how CRUD")
created = post("/api/knowhow", {
    "rule_text": "E2E test rule: all contracts need triple approval",
    "category": "compliance",
    "weight": 2
})
# POST returns {"id": ..., "message": ...}
rule_id = created.get("id")
check("create rule", bool(rule_id), f"id={rule_id}")

# PUT now returns full updated rule object
updated = http("PUT", f"/api/knowhow/{rule_id}", {
    "rule_text": "E2E test rule (updated)",
    "category": "compliance",
    "weight": 3
})
check("update rule", updated.get("weight") == 3 or "message" in updated,
      f"weight={updated.get('weight')} msg={updated.get('message')}")

deleted = http("DELETE", f"/api/knowhow/{rule_id}")
check("delete rule", "message" in deleted)

# Summary
print("\n" + "=" * 50)
if errors:
    print(f"FAILED: {len(errors)} checks failed:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print(f"ALL CHECKS PASSED ({7} groups)")

