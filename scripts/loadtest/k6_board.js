// k6 load test for TeamFlow's hot paths (M3 #37).
//
// Run against a seeded environment (scripts/seed_mock_data.py --preset heavy):
//   k6 run -e BASE_URL=https://arsene.ir/flow -e API_TOKEN=tf_xxx \
//          -e ORG=arsene -e PROJECT=<project-uuid> scripts/loadtest/k6_board.js
//
// API_TOKEN should be a personal access token (M3 API tokens) so CI load
// tests never need a human password.
import http from "k6/http";
import { check, group } from "k6";
import { Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_TOKEN = __ENV.API_TOKEN || "";
const ORG = __ENV.ORG || "arsene";
const PROJECT = __ENV.PROJECT || "";

const params = {
  headers: {
    Authorization: `Bearer ${API_TOKEN}`,
    "Content-Type": "application/json",
  },
};

export const errors = new Rate("business_errors");

export const options = {
  scenarios: {
    // Board/tree load: target p95 < 1s on a 10k-task project.
    board: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 10),
      duration: __ENV.DURATION || "30s",
      exec: "boardFlow",
    },
    // Cursor listing: target p95 < 300ms (keyset pagination).
    cursor: {
      executor: "constant-vus",
      vus: Number(__ENV.LIST_VUS || 5),
      duration: __ENV.DURATION || "30s",
      exec: "cursorFlow",
      startTime: "5s",
    },
  },
  thresholds: {
    "http_req_duration{scenario:board}": ["p(95)<1000", "p(99)<2000"],
    "http_req_duration{scenario:cursor}": ["p(95)<300", "p(99)<800"],
    business_errors: ["rate<0.01"],
    http_req_failed: ["rate<0.01"],
  },
};

function api(path) {
  return `${BASE_URL}/api/v1${path}`;
}

function track(res) {
  const ok = check(res, { "status 2xx": (r) => r.status >= 200 && r.status < 300 });
  errors.add(!ok);
  return res;
}

export function boardFlow() {
  group("board", () => {
    track(http.get(api(`/projects/${PROJECT}/tasks/tree`), params));
    track(http.get(api(`/projects/${PROJECT}/roadmap`), params));
    track(
      http.get(
        api(`/organizations/${ORG}/tasks?project_id=${PROJECT}&limit=50`),
        params
      )
    );
  });
}

export function cursorFlow() {
  group("cursor", () => {
    let cursor = null;
    for (let page = 0; page < 5; page++) {
      const url =
        api(`/organizations/${ORG}/tasks/cursor?limit=50&project_id=${PROJECT}`) +
        (cursor ? `&cursor=${encodeURIComponent(cursor)}` : "");
      const res = track(http.get(url, params));
      if (res.status !== 200) return;
      cursor = res.json("next_cursor");
      if (!cursor) return;
    }
  });
}
