-- TimeAble 그룹/멤버 스키마. data dict 모양을 복원할 수 있게 구성한다.

create table if not exists groups (
    id           text primary key,            -- 'dummy' 같은 slug
    name         text not null,
    days         text[] not null default array['Mon','Tue','Wed','Thu','Fri'],
    start_hour   int  not null default 9,
    end_hour     int  not null default 21,
    slot_minutes int  not null default 30,
    created_at   timestamptz not null default now()
);

create table if not exists members (
    id        text not null,                  -- 학생 id 's01'
    group_id  text not null references groups(id) on delete cascade,
    name      text,
    dept      text,
    year      int,
    color     text,
    busy      jsonb not null,                 -- [요일][칸] bool 격자
    primary key (group_id, id)
);

create index if not exists members_group_idx on members(group_id);
