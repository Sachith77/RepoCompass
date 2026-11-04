// Calls to the RepoCompass API. The shapes mirror src/repocompass/report.py and api.py.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Person = { login: string; count: number };

export type BandedArea = {
  area: string;
  band: string;
  merge_rate: number | null;
  mature_newcomer_prs: number;
  merged_prs: number;
  wilson_interval: [number | null, number | null];
  distinct_newcomer_authors: number;
  top_author_pr_share: number | null;
  author_concentration_flag: boolean;
  concentration_note: string | null;
  stale_open_newcomer_prs: number;
  median_hours_first_formal_review: number | null;
  formal_review_prs: number;
  median_hours_first_human_response: number | null;
  human_response_prs: number;
  no_response_share: number | null;
  no_response_base_prs: number;
  example_merged_newcomer_prs: { number: number; url: string }[];
};

export type AreaActivity = {
  area: string;
  commits_90d: number;
  commits_12mo: number;
  commit_authors_12mo: number;
  activity_band: string;
  top_contributors?: Person[];
  top_reviewers?: Person[];
};

export type MonthCounts = {
  total: number;
  bots: number;
  sampled: number;
  first: string | null;
  last: string | null;
};

export type Report = {
  repo: {
    requested_slug: string;
    canonical_slug: string;
    url: string;
    default_branch: string;
    snapshot_at: string;
  };
  where_to_start: {
    heading: string;
    repo_rate: number | null;
    repo_mature_newcomer_prs: number;
    formal_review_coverage: number | null;
    lead_response_measure: string;
    repo_median_hours_first_formal_review: number | null;
    repo_formal_review_prs: number;
    repo_median_hours_first_human_response: number | null;
    repo_human_response_prs: number;
    repo_no_response_share: number | null;
    repo_no_response_base_prs: number;
    bands: { band: string; areas: BandedArea[] }[];
    not_enough_data: { area: string; mature_newcomer_prs: number }[];
  };
  areas_map: AreaActivity[];
  sample: {
    window_start: string;
    window_end: string;
    total_prs: number;
    bot_or_non_user_prs_dropped: number;
    sampled_prs: number;
    is_sampled: boolean;
    covered_from: string | null;
    covered_to: string | null;
    prs_with_incomplete_files: number;
    prs_with_unknown_response_times: number;
    per_month: Record<string, MonthCounts>;
    note: string;
  };
  method: {
    area_rule: { threshold_share: number; max_depth: number; depths: Record<string, number> };
    excluded_dirs: string[];
    sweep_commits_excluded: number;
    parameters: Record<string, number>;
  };
};

export type Job = {
  id: number;
  requested_slug: string;
  state: "queued" | "running" | "done" | "failed";
  stage: string | null;
  progress: number;
  attempts: number;
  last_error: string | null;
  report_url: string | null;
  areas_map: AreaActivity[] | null;
};

export type RepoSummary = {
  canonical_slug: string;
  requested_slug: string;
  snapshot_at: string;
  is_sampled: boolean;
  report_url: string;
};

export type AnalyzeResult =
  | { status: "cached"; report_url: string; report: Report }
  | { status: "queued" | "running"; requested_slug: string; job_id: number; job_url: string };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, `The API at ${API_URL} could not be reached. Is it running?`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export const getRepos = () => call<{ repos: RepoSummary[] }>("/repos").then((r) => r.repos);

export async function getReport(owner: string, repo: string): Promise<Report | null> {
  try {
    return await call<Report>(`/repos/${owner}/${repo}/report`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export const getJob = (id: number) => call<Job>(`/jobs/${id}`);

export const analyze = (repoUrl: string) =>
  call<AnalyzeResult>("/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_url: repoUrl }),
  });
