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

  it("advances for a second successful refresh even when database data is unchanged", () => {
    const first = reconcileBrowserFreshness(
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
    const second = reconcileBrowserFreshness(
      first,
      [
        {
          active: true,
          key: ["data-status"],
          data: { ...dataStatus, server_time: "2026-08-21T19:28:47Z" },
          dataUpdatedAt: 200,
          status: "success",
        },
      ],
      40,
    );

    expect(second.lastSuccessfulRefreshAt).toBe("2026-08-21T19:28:47Z");
    expect(second.lastSuccessfulRefreshAt).not.toBe(
      dataStatus.data_last_modified_at,
    );
  });

  it("does not advance for navigation alone or a failed displayed query", () => {
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
    const navigation = reconcileBrowserFreshness(
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
      navigation,
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

    expect(navigation).toBe(current);
    expect(failed.lastSuccessfulRefreshAt).toBe(dataStatus.server_time);
    expect(browserFreshnessState(failed, 40)).toBe("degraded");
  });

  it("ages by browser refresh time and keeps stale state truthful after a failure", () => {
    const failed = {
      lastSuccessfulRefreshAt: dataStatus.server_time,
      lastSuccessfulRefreshPerformanceMs: 100,
      lastDataStatusUpdatedAt: 100,
      latestRefreshFailed: true,
    };

    expect(browserFreshnessState(failed, 101)).toBe("degraded");
    expect(browserFreshnessState(failed, 100 + 24 * 60 * 60 * 1000 + 1)).toBe(
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
