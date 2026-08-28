// Server components run inside Docker and reach the API through the compose
// network hostname. The browser reaches it through localhost. Pick the right
// base URL depending on where the code is running.
export function apiBase(): string {
  if (typeof window === "undefined") {
    return process.env.API_URL_INTERNAL ?? "http://localhost:8000";
  }
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`API ${path} failed with status ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Shared shapes. These mirror the FastAPI response dicts exactly (see
// backend/app/api/*.py) rather than re-deriving them from an OpenAPI schema,
// since there's no codegen step wired up yet.
// ---------------------------------------------------------------------------

export type Health = {
  status: string;
  db: boolean;
  redis: boolean;
};

// demand_score/supply_score/opportunity_score are null for niches that
// haven't cleared the eligibility floor (see scoring.py) -- null means
// "unranked," not "zero," and must never be sorted or displayed as if it
// were the lowest possible score.
export type NicheSummary = {
  id: number;
  label: string;
  top_terms: string[];
  demand_score: number | null;
  supply_score: number | null;
  opportunity_score: number | null;
  video_count: number;
  channel_count: number;
};

export type ScoreComponents = {
  video_count: number;
  median_views: number | null;
  channel_count: number;
  median_velocity: number | null;
  shrinkage_weight?: number;
  uploads_per_week: number | null;
  median_engagement: number | null;
  active_channel_count: number;
};

export type NicheDetail = NicheSummary & {
  score_components: ScoreComponents;
};

export type NichesPage = {
  items: NicheSummary[];
  limit: number;
  offset: number;
};

export type VideoSummary = {
  id: string;
  title: string;
  channel_id: string;
  view_count: number;
  like_count: number;
  comment_count: number;
  published_at: string | null;
  is_short: boolean;
};

export type NicheVideosPage = {
  items: VideoSummary[];
  limit: number;
  offset: number;
};

export type ChannelDetail = {
  id: string;
  title: string;
  description: string | null;
  custom_url: string | null;
  country: string | null;
  published_at: string | null;
  subscriber_count: number | null;
  subs_hidden: boolean;
  video_count: number;
  view_count: number;
  is_tracked: boolean;
  niche: { id: number; label: string; opportunity_score: number | null } | null;
};

export type SimilarVideo = {
  id: string;
  title: string;
  channel_id: string;
  view_count: number;
  published_at: string | null;
  distance: number;
};

export type SimilarVideosResponse = {
  video_id: string;
  items: SimilarVideo[];
};

export type SearchResponse = {
  query: string;
  items: SimilarVideo[];
};

export type BreakoutPrediction = {
  video_id: string;
  title: string;
  channel_id: string;
  view_count: number;
  published_at: string | null;
  breakout_probability: number;
  model_version: string;
};

export type BreakoutsResponse = {
  items: BreakoutPrediction[];
};

export type QuotaDay = {
  day: string;
  strategy_label: string;
  units_spent: number;
  calls_uncached: number;
  calls_cached: number;
  units_saved: number;
};

export type QuotaStatsResponse = {
  window_days: number;
  by_day: QuotaDay[];
};

// ---------------------------------------------------------------------------
// Typed fetchers. One function per resource so pages never build raw path
// strings themselves.
// ---------------------------------------------------------------------------

export async function getHealth(): Promise<Health | null> {
  try {
    return await apiGet<Health>("/api/health");
  } catch {
    return null;
  }
}

export async function getNiches(params?: { limit?: number; offset?: number }): Promise<NichesPage> {
  const limit = params?.limit ?? 20;
  const offset = params?.offset ?? 0;
  return apiGet<NichesPage>(`/api/niches?limit=${limit}&offset=${offset}`);
}

export async function getNiche(id: number): Promise<NicheDetail | null> {
  try {
    return await apiGet<NicheDetail>(`/api/niches/${id}`);
  } catch {
    return null;
  }
}

export async function getNicheVideos(
  id: number,
  params?: { limit?: number; offset?: number },
): Promise<NicheVideosPage> {
  const limit = params?.limit ?? 20;
  const offset = params?.offset ?? 0;
  return apiGet<NicheVideosPage>(`/api/niches/${id}/videos?limit=${limit}&offset=${offset}`);
}

export async function getChannel(id: string): Promise<ChannelDetail | null> {
  try {
    return await apiGet<ChannelDetail>(`/api/channels/${encodeURIComponent(id)}`);
  } catch {
    return null;
  }
}

export async function getSimilarVideos(
  videoId: string,
  limit = 10,
): Promise<SimilarVideosResponse | null> {
  try {
    return await apiGet<SimilarVideosResponse>(
      `/api/videos/${encodeURIComponent(videoId)}/similar?limit=${limit}`,
    );
  } catch {
    return null;
  }
}

export async function search(query: string, limit = 10): Promise<SearchResponse> {
  return apiGet<SearchResponse>(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}

export async function getBreakouts(limit = 20): Promise<BreakoutsResponse> {
  return apiGet<BreakoutsResponse>(`/api/predictions/breakouts?limit=${limit}`);
}

export async function getQuotaStats(days = 30): Promise<QuotaStatsResponse> {
  return apiGet<QuotaStatsResponse>(`/api/stats/quota?days=${days}`);
}
