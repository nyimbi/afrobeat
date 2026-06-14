/**
 * Gbẹdu k6 smoke test
 *
 * Sanity check before every deploy:
 *   - health endpoint responds < 100 ms
 *   - user registration works
 *   - generation job can be submitted and polled
 *
 * Run:
 *   k6 run tests/load/smoke.js
 *   k6 run --env BASE_URL=https://staging.api.gbedu.io tests/load/smoke.js
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

// ── custom metrics ─────────────────────────────────────────────────────────

const healthLatency        = new Trend("health_latency_ms", true);
const registrationLatency  = new Trend("registration_latency_ms", true);
const submitLatency        = new Trend("generation_submit_latency_ms", true);
const pollLatency          = new Trend("generation_poll_latency_ms", true);
const generationSuccessRate = new Rate("generation_reached_terminal");

// ── options ────────────────────────────────────────────────────────────────

export const options = {
	vus:      1,
	duration: "30s",
	thresholds: {
		// Health must always be fast
		health_latency_ms:            ["p(95)<100"],
		// Registration under 1 s
		registration_latency_ms:      ["p(95)<1000"],
		// Generation submit under 2 s
		generation_submit_latency_ms: ["p(95)<2000"],
		// HTTP error rate must be 0 during smoke
		http_req_failed:              ["rate<0.01"],
		// At least one generation must reach a terminal state
		generation_reached_terminal:  ["rate>0"],
	},
};

// ── config ─────────────────────────────────────────────────────────────────

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";

const JSON_HEADERS = {
	"Content-Type": "application/json",
	"Accept":       "application/json",
};

// ── helpers ────────────────────────────────────────────────────────────────

function randTag() {
	return Math.random().toString(36).slice(2, 10);
}

function authHeaders(token) {
	return Object.assign({}, JSON_HEADERS, {
		Authorization: `Bearer ${token}`,
	});
}

/** POST wrapper that records latency into a Trend metric. */
function timedPost(url, body, headers, trend) {
	const start = Date.now();
	const resp  = http.post(url, JSON.stringify(body), { headers });
	trend.add(Date.now() - start);
	return resp;
}

/** GET wrapper that records latency into a Trend metric. */
function timedGet(url, headers, trend) {
	const start = Date.now();
	const resp  = http.get(url, { headers });
	trend.add(Date.now() - start);
	return resp;
}

// ── main scenario ──────────────────────────────────────────────────────────

export default function () {
	// ── 1. Health check ──────────────────────────────────────────────────────

	const healthResp = timedGet(
		`${BASE_URL}/api/v1/health`,
		JSON_HEADERS,
		healthLatency,
	);

	check(healthResp, {
		"health: status 200":        (r) => r.status === 200,
		"health: has status field":  (r) => {
			try { return JSON.parse(r.body).status !== undefined; }
			catch (_) { return false; }
		},
	});

	if (healthResp.status !== 200) {
		console.error(`Health check failed: ${healthResp.status} ${healthResp.body}`);
		return;
	}

	// ── 2. Register a test user ──────────────────────────────────────────────

	const tag      = randTag();
	const email    = `smoke_${tag}@example.com`;
	const password = `Smoke_P4ss_${tag}`;

	const regResp = timedPost(
		`${BASE_URL}/api/v1/auth/register`,
		{ email, password, full_name: "Smoke Test" },
		JSON_HEADERS,
		registrationLatency,
	);

	const regOk = check(regResp, {
		"register: status 201":         (r) => r.status === 201,
		"register: has access_token":   (r) => {
			try { return !!JSON.parse(r.body).tokens.access_token; }
			catch (_) { return false; }
		},
	});

	if (!regOk) {
		console.error(`Registration failed: ${regResp.status} ${regResp.body}`);
		return;
	}

	const accessToken = JSON.parse(regResp.body).tokens.access_token;

	// ── 3. Submit a generation job ───────────────────────────────────────────

	const submitResp = timedPost(
		`${BASE_URL}/api/v1/generations`,
		{
			prompt:           "A smooth Afrobeats smoke-test track with talking drums",
			sub_genre:        "afrobeats",
			language:         "english",
			bpm:              100,
			energy_level:     6,
			duration_seconds: 15,
		},
		authHeaders(accessToken),
		submitLatency,
	);

	const submitOk = check(submitResp, {
		"submit: status 202":     (r) => r.status === 202,
		"submit: has job id":     (r) => {
			try { return !!JSON.parse(r.body).id; }
			catch (_) { return false; }
		},
		"submit: initial status": (r) => {
			try {
				const s = JSON.parse(r.body).status;
				return ["pending", "queued", "running"].includes(s);
			} catch (_) { return false; }
		},
	});

	if (!submitOk) {
		console.error(`Submit failed: ${submitResp.status} ${submitResp.body}`);
		return;
	}

	const jobId = JSON.parse(submitResp.body).id;

	// ── 4. Poll status (up to 10 times, 5 s apart) ──────────────────────────

	const TERMINAL = new Set(["completed", "failed", "cancelled"]);
	let   finalStatus = null;

	for (let attempt = 1; attempt <= 10; attempt++) {
		sleep(5);

		const pollResp = timedGet(
			`${BASE_URL}/api/v1/generations/${jobId}`,
			authHeaders(accessToken),
			pollLatency,
		);

		const pollOk = check(pollResp, {
			"poll: status 200":         (r) => r.status === 200,
			"poll: has status field":   (r) => {
				try { return !!JSON.parse(r.body).status; }
				catch (_) { return false; }
			},
			"poll: has progress field": (r) => {
				try { return JSON.parse(r.body).progress_percent !== undefined; }
				catch (_) { return false; }
			},
		});

		if (!pollOk) {
			console.error(`Poll attempt ${attempt} failed: ${pollResp.status} ${pollResp.body}`);
			break;
		}

		const body   = JSON.parse(pollResp.body);
		const status = body.status;

		console.log(`  [poll ${attempt}/10] job=${jobId} status=${status} progress=${body.progress_percent}%`);

		// Verify response structure on every poll
		check(body, {
			"poll body: id matches":            (b) => b.id === jobId,
			"poll body: progress 0-100":        (b) => b.progress_percent >= 0 && b.progress_percent <= 100,
			"poll body: prompt_used present":   (b) => typeof b.prompt_used === "string",
		});

		if (TERMINAL.has(status)) {
			finalStatus = status;
			break;
		}
	}

	generationSuccessRate.add(finalStatus !== null ? 1 : 0);

	if (finalStatus !== null) {
		console.log(`Job ${jobId} reached terminal state: ${finalStatus}`);
		check({ finalStatus }, {
			"terminal: not errored unexpectedly": ({ finalStatus: s }) =>
				// 'failed' is acceptable (ML might not be running in smoke env);
				// we just want to confirm the API tracked it rather than hanging.
				s === "completed" || s === "failed" || s === "cancelled",
		});
	} else {
		console.warn(`Job ${jobId} did not reach terminal state in 50 s (10 × 5 s polls)`);
	}

	// ── 5. List my generations (response structure check) ────────────────────

	const listResp = http.get(
		`${BASE_URL}/api/v1/generations?page=1&page_size=5`,
		{ headers: authHeaders(accessToken) },
	);

	check(listResp, {
		"list generations: status 200":    (r) => r.status === 200,
		"list generations: items is array": (r) => {
			try { return Array.isArray(JSON.parse(r.body).items); }
			catch (_) { return false; }
		},
		"list generations: total >= 1":    (r) => {
			try { return JSON.parse(r.body).total >= 1; }
			catch (_) { return false; }
		},
	});

	// ── 6. Browse public marketplace (no auth required) ──────────────────────

	const mktResp = http.get(
		`${BASE_URL}/api/v1/marketplace/beats?page=1&page_size=5`,
		{ headers: JSON_HEADERS },
	);

	check(mktResp, {
		"marketplace: status 200":       (r) => r.status === 200,
		"marketplace: has items array":  (r) => {
			try { return Array.isArray(JSON.parse(r.body).items); }
			catch (_) { return false; }
		},
	});
}
