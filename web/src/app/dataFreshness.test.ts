import { describe, expect, it } from "vitest";

import {
  browserFreshnessState,
  reconcileBrowserFreshness,
} from "./browserFreshness";
import { formatLastRefreshed, freshnessState } from "./dataFreshness";

const dataStatus = {
  status: "available" as const,
  data_revision: 3,
  data_last_modified_at: "2026-07-21T19:27:18Z",
  server_time: "2026-08-21T19:28:00Z",
};

describe("data freshness presentation", () => {
  it("records server refresh time even when the database mutation is old", () => {
    const refresh = reconcileBrowserFreshness(
      { latestRefreshFailed: false },
      [
        {
          active: true,
          key: ["data-status"],
          data: dataStatus,
          dataUpdatedAt: 100,
          status: "success",
        },
      ],
      20,
    );

    expect(refresh.lastSuccessfulRefreshAt).toBe(dataStatus.server_time);
    expect(freshnessState(refresh, 21)).toBe("healthy");
  });

  it("does not advance for a rerender or failed displayed data query", () => {
    const current = reconcileBrowserFreshness(
      { latestRefreshFailed: false },
      [
        {
          active: true,
          key: ["data-status"],
          data: dataStatus,
          dataUpdatedAt: 100,
          status: "success",
        },
      ],
      20,
    );
    const rerender = reconcileBrowserFreshness(
      current,
      [
        {
          active: true,
          key: ["data-status"],
          data: dataStatus,
          dataUpdatedAt: 100,
          status: "success",
        },
      ],
      30,
    );
    const failed = reconcileBrowserFreshness(
      rerender,
      [
        {
          active: true,
          key: ["data-status"],
          data: { ...dataStatus, server_time: "2026-08-21T19:30:00Z" },
          dataUpdatedAt: 200,
          status: "success",
        },
        {
          active: true,
          key: ["library", "eoats"],
          data: undefined,
          dataUpdatedAt: 0,
          status: "error",
        },
      ],
      40,
    );

    expect(rerender).toBe(current);
    expect(failed.lastSuccessfulRefreshAt).toBe(dataStatus.server_time);
    expect(browserFreshnessState(failed, 40)).toBe("degraded");
  });

  it("advances after every successful active-data refresh and ages by refresh age", () => {
    const current = reconcileBrowserFreshness(
      { latestRefreshFailed: false },
      [
        {
          active: true,
          key: ["data-status"],
          data: { ...dataStatus, server_time: "2026-08-21T19:31:00Z" },
          dataUpdatedAt: 200,
          status: "success",
        },
        {
          active: true,
          key: ["library", "eoats"],
          data: [],
          dataUpdatedAt: 190,
          status: "success",
        },
      ],
      100,
    );

    expect(current.lastSuccessfulRefreshAt).toBe("2026-08-21T19:31:00Z");
    expect(browserFreshnessState(current, 24 * 60 * 60 * 1000 + 101)).toBe(
      "stale",
    );
  });

  it("waits for every active displayed query to finish before recording", () => {
    const previous = {
      lastSuccessfulRefreshAt: "2026-08-21T19:28:00Z",
      lastSuccessfulRefreshPerformanceMs: 20,
      lastDataStatusUpdatedAt: 100,
      latestRefreshFailed: false,
    };
    const pending = reconcileBrowserFreshness(
      previous,
      [
        {
          active: true,
          key: ["data-status"],
          data: { ...dataStatus, server_time: "2026-08-21T19:32:00Z" },
          dataUpdatedAt: 300,
          status: "success",
        },
        {
          active: true,
          key: ["library", "eoats"],
          data: [],
          dataUpdatedAt: 190,
          fetching: true,
          status: "success",
        },
      ],
      200,
    );

    expect(pending).toBe(previous);
  });

  it("uses a compact date and time separated by a middle dot", () => {
    expect(formatLastRefreshed(dataStatus.server_time)).toContain(" · ");
  });
});
