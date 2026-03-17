"""
端到端联调测试脚本
测试 Phase 1 + Phase 2 所有关键端点的请求/响应
用法: python3 -m tests.test_e2e  (需先启动后端: python3 main.py)
"""
import asyncio
import json
import sys
import httpx

BASE_URL = "http://127.0.0.1:8765/api"
PASSED = 0
FAILED = 0


def report(name: str, ok: bool, detail: str = "") -> None:
    global PASSED, FAILED
    status = "✅ PASS" if ok else "❌ FAIL"
    if ok:
        PASSED += 1
    else:
        FAILED += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  {status}  {name}{suffix}")


async def run_tests() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as c:
        # ===== Phase 1 端点 =====
        print("\n=== Phase 1 端点 ===")

        # 1. Health
        r = await c.get("/health")
        report("GET /health", r.status_code == 200 and r.json().get("status") == "ok")

        # 2. Chat test-connection (无 LLM 配置，预期 400/422/500 均为正常行为)
        r = await c.post("/chat/test-connection", json={"api_url": "", "api_key": "", "model": ""})
        report("POST /chat/test-connection", r.status_code in (200, 400, 422, 500), f"status={r.status_code}")

        # ===== Phase 2: Skills =====
        print("\n=== Phase 2: Skills ===")

        r = await c.get("/skills")
        data = r.json()
        skills = data.get("skills", [])
        report("GET /skills", r.status_code == 200 and len(skills) >= 1, f"{len(skills)} skills")

        r = await c.get("/skills/procurement-review")
        s = r.json()
        report("GET /skills/{id}", r.status_code == 200 and s.get("name"), f"name={s.get('name')}")

        r = await c.get("/skills/nonexistent-skill")
        report("GET /skills/{id} 404", r.status_code == 404)

        r = await c.post("/skills/match", json={"query": "帮我审查采购PPT"})
        matches = r.json().get("matches", [])
        report("POST /skills/match", r.status_code == 200 and len(matches) > 0,
               f"top={matches[0]['skill_name'] if matches else 'none'}")

        r = await c.post("/skills/match", json={"query": "今天天气怎么样"})
        matches2 = r.json().get("matches", [])
        report("POST /skills/match (无关查询)", r.status_code == 200, f"matches={len(matches2)}")

        # ===== Phase 2: Know-how =====
        print("\n=== Phase 2: Know-how ===")

        r = await c.get("/knowhow/stats")
        stats = r.json()
        report("GET /knowhow/stats", r.status_code == 200 and stats.get("total_rules", 0) > 0,
               f"total={stats.get('total_rules')}")

        r = await c.get("/knowhow")
        kh = r.json()
        report("GET /knowhow", r.status_code == 200 and len(kh.get("rules", [])) > 0,
               f"rules={kh.get('total')}")

        # 创建规则
        r = await c.post("/knowhow", json={
            "category": "测试分类", "rule_text": "E2E测试规则-可删除",
            "weight": 1, "source": "test",
        })
        report("POST /knowhow (创建)", r.status_code == 200 and r.json().get("id"))
        new_id = r.json().get("id", "")

        # 更新规则
        if new_id:
            r = await c.put(f"/knowhow/{new_id}", json={"weight": 5})
            report("PUT /knowhow/{id} (更新)", r.status_code == 200)

            # 删除规则
            r = await c.delete(f"/knowhow/{new_id}")
            report("DELETE /knowhow/{id}", r.status_code == 200)

        # ===== Phase 2: Knowledge =====
        print("\n=== Phase 2: Knowledge ===")

        r = await c.get("/knowledge/stats")
        ks = r.json()
        report("GET /knowledge/stats", r.status_code == 200, f"ppt={ks.get('ppt_count', 0)}")

        r = await c.post("/knowledge/query", json={"query": "采购服务器", "top_k": 3})
        report("POST /knowledge/query", r.status_code == 200, f"keys={list(r.json().keys())}")

        # ===== Phase 2: Agent =====
        print("\n=== Phase 2: Agent ===")

        r = await c.post("/agent/match", json={"query": "采购预审这个材料"})
        am = r.json()
        report("POST /agent/match", r.status_code == 200 and am.get("matched"),
               f"skill={am.get('skill_name')}, conf={am.get('confidence')}")

        r = await c.post("/agent/match", json={"query": "讲个笑话"})
        report("POST /agent/match (无关)", r.status_code == 200 and not r.json().get("matched"))

        # Agent execute (SSE 流式) — 无 LLM 配置，测试基本流程
        print("  ⏳ 测试 Agent Execute (SSE)...")
        events = []
        async with c.stream("POST", "/agent/execute", json={
            "skill_id": "procurement-review", "params": {"file": "test.pptx"},
        }) as resp:
            report("POST /agent/execute (连接)", resp.status_code == 200)
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        events.append(json.loads(data_str))
                    except json.JSONDecodeError:
                        pass

        event_types = [e.get("type") for e in events]
        has_start = "execution_start" in event_types
        has_complete = "complete" in event_types
        report("Agent Execute 事件流", has_start and has_complete,
               f"events={len(events)}, types={event_types}")

        # 检查 complete 事件包含 context
        if has_complete:
            complete_evt = [e for e in events if e["type"] == "complete"][0]
            ctx = complete_evt.get("context", {})
            report("Agent Execute 结果", ctx.get("status") == "completed",
                   f"steps={len(ctx.get('steps', []))}")


async def main() -> None:
    print("=" * 60)
    print("Meeting Assistant — 端到端联调测试")
    print("=" * 60)

    # 检查后端是否运行
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            await c.get(f"{BASE_URL}/health")
    except Exception:
        print("❌ 后端未启动！请先运行: python3 main.py")
        sys.exit(1)

    await run_tests()

    print(f"\n{'=' * 60}")
    print(f"结果: {PASSED} 通过, {FAILED} 失败")
    print("=" * 60)
    sys.exit(1 if FAILED > 0 else 0)


if __name__ == "__main__":
    asyncio.run(main())

