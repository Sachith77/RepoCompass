-- RepoCompass schema. Five tables, no ORM.
-- Applied idempotently by repocompass.db.apply_schema.

CREATE TABLE IF NOT EXISTS repos (
    id                  bigserial PRIMARY KEY,
    requested_slug      text        NOT NULL,
    canonical_slug      text        NOT NULL,
    default_branch      text,
    snapshot_at         timestamptz,
    window_start        timestamptz,
    window_end          timestamptz,
    -- the area rule fitted to this repo's own file tree, and what was left out:
    -- {"threshold_share": .., "max_depth": .., "depths": {"<top dir>": levels}}
    area_depths         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    excluded_dirs       jsonb       NOT NULL DEFAULT '[]'::jsonb,
    -- the metric parameters this analysis used, so the report never shows today's settings
    parameters          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    -- commits ignored for activity because they touched more than the sweep share of areas
    sweep_commits_excluded integer,
    -- sampling record: a report must be able to state exactly what it saw
    -- human-authored PRs only; PRs by bots, deleted accounts and other non-users are
    -- counted separately (bot_prs_in_window) and dropped before sampling
    total_prs_in_window integer,
    bot_prs_in_window   integer,
    sampled_prs         integer,
    -- {"YYYY-MM": {"total", "bots", "sampled", "first", "last"}}
    prs_per_month       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    is_sampled          boolean     NOT NULL DEFAULT false,
    -- the creation times of the oldest and newest sampled PR: the dates actually covered
    sample_first_created timestamptz,
    sample_last_created  timestamptz,
    -- repo-wide mature newcomer merge rate: the comparison point for every band
    repo_merge_rate     double precision,
    repo_mature_newcomer_prs integer,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT repos_canonical_slug_key UNIQUE (canonical_slug)
);

CREATE INDEX IF NOT EXISTS repos_requested_slug_idx ON repos (requested_slug);

CREATE TABLE IF NOT EXISTS prs (
    repo_id                   bigint   NOT NULL REFERENCES repos (id) ON DELETE CASCADE,
    number                    integer  NOT NULL,
    -- only human-authored PRs are stored
    author_login              text     NOT NULL,
    -- stored for the method page's comparison only; never used to decide newcomer status
    author_association        text,
    created_at                timestamptz NOT NULL,
    merged_at                 timestamptz,
    closed_at                 timestamptz,
    -- GitHub's PullRequestState values
    state                     text     NOT NULL,
    is_merged                 boolean  NOT NULL DEFAULT false,
    changed_files             integer,
    -- false when the file list could not be paginated in full; such PRs are excluded.
    -- No default on purpose: ingest must say whether it fetched every file.
    files_complete            boolean  NOT NULL,
    is_newcomer               boolean  NOT NULL DEFAULT false,
    first_formal_review_at    timestamptz,
    first_human_response_at   timestamptz,
    -- false when the fetched reviews/comments were cut short before any human answer
    response_times_complete   boolean  NOT NULL,
    PRIMARY KEY (repo_id, number),
    CONSTRAINT prs_state_check
        CHECK (state IN ('OPEN', 'CLOSED', 'MERGED'))
);

CREATE INDEX IF NOT EXISTS prs_repo_created_idx ON prs (repo_id, created_at);
CREATE INDEX IF NOT EXISTS prs_repo_newcomer_idx ON prs (repo_id, is_newcomer);
CREATE INDEX IF NOT EXISTS prs_repo_author_idx ON prs (repo_id, author_login);

-- Many-to-many by design: a PR tying across areas counts for each tied area.
CREATE TABLE IF NOT EXISTS pr_areas (
    repo_id     bigint  NOT NULL,
    pr_number   integer NOT NULL,
    area        text    NOT NULL,
    file_count  integer NOT NULL,
    PRIMARY KEY (repo_id, pr_number, area),
    FOREIGN KEY (repo_id, pr_number) REFERENCES prs (repo_id, number) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS pr_areas_repo_area_idx ON pr_areas (repo_id, area);

CREATE TABLE IF NOT EXISTS area_stats (
    repo_id                 bigint NOT NULL REFERENCES repos (id) ON DELETE CASCADE,
    area                    text   NOT NULL,
    mature_newcomer_prs     integer NOT NULL DEFAULT 0,
    merged_prs              integer NOT NULL DEFAULT 0,
    merge_rate              double precision,
    wilson_low              double precision,
    wilson_high             double precision,
    -- 'above repo average' | 'below repo average' | 'no clear difference' | 'not enough data'
    band                    text,
    meets_min_sample        boolean NOT NULL DEFAULT false,
    -- sample-quality signals: 12 PRs from 3 people is not 12 PRs from 12
    distinct_newcomer_authors integer NOT NULL DEFAULT 0,
    top_author_pr_share     double precision,
    author_concentration_flag boolean NOT NULL DEFAULT false,
    -- newcomer PRs still open past the configured age; deliberately outside merge_rate
    stale_open_newcomer_prs integer NOT NULL DEFAULT 0,
    -- medians over newcomer PRs that got a response, with how many PRs each covers
    median_hours_first_formal_review  double precision,
    formal_review_prs       integer NOT NULL DEFAULT 0,
    median_hours_first_human_response double precision,
    human_response_prs      integer NOT NULL DEFAULT 0,
    -- share of mature newcomer PRs with no human response within the configured days
    no_response_share       double precision,
    no_response_base_prs    integer NOT NULL DEFAULT 0,
    -- activity from the clone: non-merge, non-bot, non-sweep commits
    commits_90d             integer NOT NULL DEFAULT 0,
    commits_12mo            integer NOT NULL DEFAULT 0,
    commit_authors_12mo     integer NOT NULL DEFAULT 0,
    -- 'active' | 'steady' | 'dormant'
    activity_band           text,
    -- [{"login": .., "count": ..}] from PR data: merged PRs authored, reviews submitted
    top_contributors        jsonb   NOT NULL DEFAULT '[]'::jsonb,
    top_reviewers           jsonb   NOT NULL DEFAULT '[]'::jsonb,
    computed_at             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repo_id, area)
);

CREATE TABLE IF NOT EXISTS jobs (
    id          bigserial PRIMARY KEY,
    repo_id     bigint      REFERENCES repos (id) ON DELETE CASCADE,
    requested_slug text     NOT NULL,
    state       text        NOT NULL DEFAULT 'queued',
    stage       text,
    progress    integer     NOT NULL DEFAULT 0,
    -- resume point, so an interrupted run continues instead of restarting
    checkpoint  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    attempts    integer     NOT NULL DEFAULT 0,
    last_error  text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT jobs_state_check
        CHECK (state IN ('queued', 'running', 'done', 'failed')),
    CONSTRAINT jobs_progress_check
        CHECK (progress BETWEEN 0 AND 100)
);

-- The worker claims work with FOR UPDATE SKIP LOCKED ordered by this index.
CREATE INDEX IF NOT EXISTS jobs_claim_idx ON jobs (state, created_at);
