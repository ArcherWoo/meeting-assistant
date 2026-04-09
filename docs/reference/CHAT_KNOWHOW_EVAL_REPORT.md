# Chat Knowhow 评测报告

- 模式：`heuristic`
- 样本数：`12`
- 实际执行：`11`
- 通过：`11`
- 失败：`0`

## 指标

- 通过率：`100.0%`
- 平均总耗时：`15.18 ms`
- P95 总耗时：`21 ms`
- 平均规划耗时：`0 ms`
- 平均 knowhow 耗时：`15.09 ms`
- 平均每例 LLM 调用数：`0`

## 明细

| case | result | planner knowhow | knowhow count | total ms | llm calls | reason |
| --- | --- | --- | --- | --- | --- | --- |
| `skip-greeting` | `pass` | `False` | `0` | `13` | `0` | skip_ok |
| `skip-translation` | `pass` | `False` | `0` | `12` | `0` | skip_ok |
| `rule-supplier-qualification` | `pass` | `True` | `1` | `13` | `0` | rule_hit_ok |
| `rule-single-source` | `pass` | `True` | `1` | `21` | `0` | rule_hit_ok |
| `rule-price-reasonable` | `pass` | `True` | `1` | `15` | `0` | rule_hit_ok |
| `rule-payment-clause` | `pass` | `True` | `1` | `16` | `0` | rule_hit_ok |
| `rule-delivery-plan` | `pass` | `True` | `1` | `13` | `0` | rule_hit_ok |
| `library-stats` | `pass` | `True` | `1` | `19` | `0` | library_summary_ok |
| `library-categories` | `pass` | `True` | `1` | `17` | `0` | library_summary_ok |
| `rule-file-risk` | `pass` | `True` | `1` | `16` | `0` | rule_hit_ok |
| `skip-polish` | `pass` | `False` | `0` | `12` | `0` | skip_ok |
| `llm-route-vendor-onboarding` | `skipped` | `False` | `0` | `0` | `0` | requires_llm |
