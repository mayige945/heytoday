version: v1
schema: news-scoring/v1
prompt_name: risk_review

# 安全复核 Prompt（risk_review v1）

用于在二级评分之后，对事件的**安全判定**做一次独立复核（可选，人工触发）。只输出与
`news-scoring/v1` 中安全相关字段一致的子结构，供 `safety_override` 使用。

## 输出 JSON

```json
{
  "schema_version": "news-scoring/v1",
  "safety_tier": "redline | sensitive | default | uncertain",
  "safety_tags": [],
  "safety_reason": "...",
  "safety_uncertain": false,
  "safety_assessments": {
    "upper_primary": {"conservative": "eligible|ineligible", "standard": "eligible|ineligible", "open": "eligible|ineligible"},
    "junior_high": {"conservative": "eligible|ineligible", "standard": "eligible|ineligible", "open": "eligible|ineligible"}
  }
}
```

## 判定原则（直接执行 Content_Safety_Policy）

1. 先问「它会不会伤到一个孩子？」——图像化暴力/血腥、性或未成年人性化、自残方法/美化、
   仇恨煽动、危险行为可操作指引、极端主义美化 → **红线**，六组合全部 `ineligible`，永不可调。
2. 再问「换个角度切，能不能变成一件值得想的事？」——死亡/战争/灾难/犯罪/疾病/社会争议属
   **敏感但重要**，按家长档 × 年龄档决定进/不进/带提示；年龄档是底线，开放的小学不比标准的初中更重。
3. 最后「如果聊，孩子是被给了一个出口，还是被留在恐惧里？」——没有出口的，标 uncertain 或更严。

`safety_override` **只允许把事件判得更严，或在补充证据后解除 uncertain，绝不允许放宽红线**。
只输出 JSON，无额外文字。
