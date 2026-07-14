create table if not exists public.news_material_sync_runs (
  sync_id text primary key,
  schema_version text not null,
  material_generated_at timestamptz not null,
  result text not null,
  event_count integer not null,
  content_sha256 text not null unique,
  status text not null,
  started_at timestamptz not null,
  finished_at timestamptz,
  error_message text,

  constraint news_material_sync_runs_result_check
    check (result in ('populated', 'empty')),
  constraint news_material_sync_runs_status_check
    check (status in ('syncing', 'success', 'failed')),
  constraint news_material_sync_runs_event_count_check
    check (event_count >= 0),
  constraint news_material_sync_runs_sha256_check
    check (char_length(content_sha256) = 64)
);

create table if not exists public.news_material_events (
  sync_id text not null references public.news_material_sync_runs(sync_id) on delete cascade,
  event_id text not null,
  title text not null,
  summary text,
  primary_category text not null,
  topic_categories jsonb not null default '[]'::jsonb,
  child_hook text,
  age_assessments jsonb not null default '{}'::jsonb,
  safety_tier text not null,
  safety_tags jsonb not null default '[]'::jsonb,
  safety_reason text,
  needs_fact_check boolean not null,
  fact_check_targets jsonb not null default '[]'::jsonb,
  source_count integer not null,
  sources jsonb not null,
  scores jsonb not null default '{}'::jsonb,
  human_review jsonb,
  payload jsonb not null,
  synced_at timestamptz not null default now(),

  primary key (sync_id, event_id),
  constraint news_material_events_safety_check
    check (safety_tier in ('sensitive', 'default', 'uncertain')),
  constraint news_material_events_source_count_check
    check (source_count >= 1)
);

create index if not exists idx_news_material_sync_runs_latest
  on public.news_material_sync_runs (status, material_generated_at desc);

create index if not exists idx_news_material_events_event
  on public.news_material_events (event_id);

create index if not exists idx_news_material_events_category
  on public.news_material_events (primary_category);

create index if not exists idx_news_material_events_safety
  on public.news_material_events (safety_tier);

alter table public.news_material_sync_runs enable row level security;
alter table public.news_material_events enable row level security;

revoke all privileges on public.news_material_sync_runs from public, anon, authenticated;
revoke all privileges on public.news_material_events from public, anon, authenticated;
grant select, insert, update on public.news_material_sync_runs to service_role;
grant select, insert, update on public.news_material_events to service_role;

drop policy if exists news_material_sync_runs_no_public_access
  on public.news_material_sync_runs;
create policy news_material_sync_runs_no_public_access
  on public.news_material_sync_runs
  as restrictive
  for all
  to anon, authenticated
  using (false)
  with check (false);

drop policy if exists news_material_events_no_public_access
  on public.news_material_events;
create policy news_material_events_no_public_access
  on public.news_material_events
  as restrictive
  for all
  to anon, authenticated
  using (false)
  with check (false);

create or replace view public.latest_news_material_events
with (security_invoker = true) as
select events.*
from public.news_material_events as events
where events.sync_id = (
  select runs.sync_id
  from public.news_material_sync_runs as runs
  where runs.status = 'success'
  order by runs.material_generated_at desc, runs.finished_at desc nulls last
  limit 1
);

revoke all privileges on public.latest_news_material_events from public, anon, authenticated;
grant select on public.latest_news_material_events to service_role;

comment on table public.news_material_sync_runs is '新闻素材库同步批次：每份 news-material/v1 导出对应一个不可变快照，只有 success 批次会进入最新素材库视图。';
comment on table public.news_material_events is '新闻素材库事件快照：按同步批次保存完整事件，采集阶段只排除红线，年龄与事实核验字段仅作下游参考。';
comment on view public.latest_news_material_events is '最新新闻素材库事件视图：只展示 material_generated_at 最新且同步成功的完整快照。';

comment on column public.news_material_sync_runs.sync_id is '同步批次主键，由规范化素材库 JSON 的 SHA-256 前 32 位生成。';
comment on column public.news_material_sync_runs.schema_version is '素材库 JSON Schema 版本，当前为 news-material/v1。';
comment on column public.news_material_sync_runs.material_generated_at is '本地素材库生成时间，保留原始时区语义。';
comment on column public.news_material_sync_runs.result is '素材库结果：populated=有事件，empty=合法空库。';
comment on column public.news_material_sync_runs.event_count is '该快照包含的事件数量。';
comment on column public.news_material_sync_runs.content_sha256 is '规范化完整素材库 JSON 的 SHA-256，用于幂等与内容校验。';
comment on column public.news_material_sync_runs.status is '同步状态：syncing、success 或 failed。';
comment on column public.news_material_sync_runs.started_at is '远端同步开始时间。';
comment on column public.news_material_sync_runs.finished_at is '远端同步完成或失败时间。';
comment on column public.news_material_sync_runs.error_message is '同步失败摘要，最长由客户端限制为 1000 字符，不含密钥。';

comment on column public.news_material_events.sync_id is '所属同步批次，关联 news_material_sync_runs。';
comment on column public.news_material_events.event_id is '本地新闻事件稳定 ID；与 sync_id 组成快照内主键。';
comment on column public.news_material_events.title is '新闻事件标题。';
comment on column public.news_material_events.summary is '新闻事件概述。';
comment on column public.news_material_events.primary_category is '六类选题主分类。';
comment on column public.news_material_events.topic_categories is '话题分类数组，JSONB。';
comment on column public.news_material_events.child_hook is '面向孩子的讨论入口。';
comment on column public.news_material_events.age_assessments is '小学高年级与初中年龄兴趣参考标签，JSONB，不作入库门槛。';
comment on column public.news_material_events.safety_tier is '安全分级：default、sensitive 或 uncertain；redline 已在导出前排除。';
comment on column public.news_material_events.safety_tags is '安全风险标签数组，JSONB。';
comment on column public.news_material_events.safety_reason is '安全分级理由。';
comment on column public.news_material_events.needs_fact_check is '是否提示下游在写稿前核验，不作素材库入库门槛。';
comment on column public.news_material_events.fact_check_targets is '待核验事实点数组，JSONB。';
comment on column public.news_material_events.source_count is '事件聚合的来源数量。';
comment on column public.news_material_events.sources is '来源名称、角色、URL 与发布时间数组，JSONB。';
comment on column public.news_material_events.scores is '故事性、讨论价值、知识增量等结构化评分，JSONB。';
comment on column public.news_material_events.human_review is '可选人工策展记录；未策展时为 null。';
comment on column public.news_material_events.payload is 'news-material/v1 中该事件的完整原始 JSON，便于无损回放。';
comment on column public.news_material_events.synced_at is '该事件快照写入 Supabase 的时间。';
