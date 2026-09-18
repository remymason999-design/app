const { test, expect } = require("@playwright/test");

const friendId = "scroll-regression-friend";
const titles = Array.from({ length: 24 }, (_, index) => ({
  id: `title-${index + 1}`,
  title: `Title ${String(index + 1).padStart(2, "0")}`,
  type: index % 3 === 0 ? "tv" : "movie",
  rating: 9 - index / 20,
  year: 2026 - (index % 10),
  runtime: 100,
  seasons: index % 3 === 0 ? [{ season_number: 1 }] : undefined,
  poster_url: `/e2e/poster/${index + 1}.svg`,
  progress: index % 3 === 0 ? { season: 1, episode: 2 } : undefined,
}));

const user = {
  user_id: "scroll-regression-user",
  name: "Regression User",
  onboarding_completed: true,
  subscriptions: [],
  saved: titles.map((title) => title.id),
  watched: titles.map((title) => title.id),
};

const comparePayload = {
  you: { name: "You" },
  them: { name: "Alex Friend" },
  overlap: titles,
  only_me: titles,
  only_them: titles,
  saved: {
    both: titles,
    you: titles,
    friend: titles,
  },
  watched: {
    both: titles,
    you: titles,
    friend: titles,
  },
  recommendations: titles.map((title) => ({
    ...title,
    reason: "A strong match for both of you",
  })),
  pick_tonight: titles[0],
  sentiment: {
    you: { "title-1": "loved" },
    friend: { "title-1": "liked" },
  },
  progress: {
    you: { "title-1": { season: 1, episode: 2 } },
    friend: { "title-1": { season: 1, episode: 4 } },
  },
  synced_at: "2026-09-17T12:00:00Z",
};

async function installMocks(page) {
  let comparePoll = 0;
  await page.addInitScript(() => {
    localStorage.setItem("ws_access_token", "e2e-token");
    localStorage.setItem("ws_tutorial_v1_seen", "1");
  });

  await page.route("**/e2e/poster/*.svg", async (route) => {
    // A delay makes the regression journey exercise lazy image loading after scroll.
    await new Promise((resolve) => setTimeout(resolve, 80));
    const number = route.request().url().match(/(\d+)\.svg$/)?.[1] || "0";
    await route.fulfill({
      contentType: "image/svg+xml",
      body: `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="300"><rect width="100%" height="100%" fill="#25140d"/><text x="100" y="155" text-anchor="middle" fill="#ff7a18" font-size="32">${number}</text></svg>`,
    });
  });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");
    let body = {};

    if (path === "/auth/me") body = user;
    else if (path === "/library") {
      body = {
        saved: titles,
        watched: titles,
        continue_watching: titles.filter((title) => title.type === "tv").slice(0, 3),
        stats: { watched_movies: 16, tv_started: 8, tv_completed: 2, watched_episodes: 42, hours: 67 },
      };
    } else if (path === `/share/compare/${friendId}`) {
      comparePoll += 1;
      body = {
        ...comparePayload,
        synced_at: new Date(Date.parse(comparePayload.synced_at) + comparePoll * 3_000).toISOString(),
      };
    }
    else if (/^\/movies\/[^/]+$/.test(path)) {
      const id = path.split("/").pop();
      body = titles.find((title) => title.id === id) || titles[0];
    } else if (path.endsWith("/reviews")) body = { summary: {}, user: [], tmdb: [] };
    else if (path.endsWith("/similar") || path === "/services") body = [];
    else if (request.method() === "POST") body = { ok: true };

    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

async function expectStableScroll(page, action, tolerance = 2) {
  const before = await page.evaluate(() => window.scrollY);
  await action();
  const after = await page.evaluate(() => window.scrollY);
  expect(Math.abs(after - before), `vertical offset moved from ${before}px to ${after}px`).toBeLessThanOrEqual(tolerance);
}

async function setScrollOffset(page, offset) {
  await expect.poll(async () => {
    await page.evaluate((top) => window.scrollTo({ top, behavior: "instant" }), offset);
    return page.evaluate((top) => Math.abs(window.scrollY - top), offset);
  }).toBeLessThanOrEqual(2);
  await page.waitForTimeout(150);
}

test.beforeEach(async ({ page }) => {
  await installMocks(page);
});

test("Library keeps practical position through posters, refresh, filters, details and progress edits", async ({ page }) => {
  await page.goto("/watchlist");
  await expect(page.getByTestId("library-page")).toBeVisible();
  await expect(page.locator('[data-testid^="watchlist-item-"]')).toHaveCount(24);

  await setScrollOffset(page, 900);
  await expectStableScroll(page, () => page.waitForTimeout(250));
  await expectStableScroll(page, () => page.evaluate(() => window.dispatchEvent(new Event("focus"))));
  await page.waitForTimeout(150);

  await page.getByTestId("library-filter-tv").evaluate((button) => button.click());
  await expect(page.getByTestId("library-filter-tv")).toHaveClass(/bg-amber/);
  // A shrinking result set may clamp the offset to its new maximum, but must
  // not reset the user to the top.
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(200);
  await page.getByTestId("library-filter-all").evaluate((button) => button.click());
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(200);

  await page.getByTestId("library-tab-watched").click();
  await page.getByTestId("library-filter-tv").click();
  await setScrollOffset(page, 400);
  const returnOffset = await page.evaluate(() => window.scrollY);
  await page.locator('[data-testid^="watched-item-"] a').nth(2).click();
  await expect(page).toHaveURL(/\/movie\/title-/);
  await page.goBack();
  await expect(page.getByTestId("library-page")).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(returnOffset - 120);
  await expect(page.getByTestId("library-tab-watched")).toHaveClass(/bg-amber/);
  await expect(page.getByTestId("library-filter-tv")).toHaveClass(/bg-amber/);

  const tvItem = page.locator('[data-testid^="watched-item-"]').filter({ has: page.getByText(/S1 E2/) }).first();
  await tvItem.getByText("S1 E2").last().click();
  const editor = page.locator('[data-testid^="progress-editor-"]');
  await expect(editor).toBeVisible();
  await editor.getByRole("button", { name: "Mark season" }).click();
  await expect(editor).toBeHidden();
});

test("Compare Friends paginates without duplicate requests, cards, or scroll growth", async ({ page }) => {
  const expectedPageSize = page.viewportSize().width <= 640 ? 12 : 20;
  const expectedSecondPageSize = titles.length - expectedPageSize;
  let compareRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === `/api/share/compare/${friendId}`) compareRequests += 1;
  });

  await page.goto(`/compare/${friendId}`);
  await expect(page.getByTestId("compare-page")).toBeVisible();
  await expect(page.getByTestId("compare-page-indicator")).toHaveText("Page 1 of 2");
  await expect(page.locator('[data-testid^="compare-card-"]')).toHaveCount(expectedPageSize);

  const pageOneIds = await page.locator('[data-testid^="compare-card-"]').evaluateAll(
    (cards) => cards.map((card) => card.getAttribute("data-testid"))
  );
  expect(new Set(pageOneIds).size).toBe(pageOneIds.length);

  await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" }));
  const pageOneHeight = await page.evaluate(() => document.body.scrollHeight);
  const requestsAtIdle = compareRequests;
  await page.waitForTimeout(3_500);
  expect(compareRequests).toBe(requestsAtIdle);
  expect(await page.evaluate(() => document.body.scrollHeight)).toBe(pageOneHeight);
  await expect(page.locator('[data-testid^="compare-card-"]')).toHaveCount(expectedPageSize);

  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByTestId("compare-page-indicator")).toHaveText("Page 2 of 2");
  await expect(page.locator('[data-testid^="compare-card-"]')).toHaveCount(expectedSecondPageSize);
  const pageTwoIds = await page.locator('[data-testid^="compare-card-"]').evaluateAll(
    (cards) => cards.map((card) => card.getAttribute("data-testid"))
  );
  expect(new Set(pageTwoIds).size).toBe(pageTwoIds.length);
  expect(pageTwoIds.some((id) => pageOneIds.includes(id))).toBe(false);

  await page.getByRole("button", { name: "Previous" }).click();
  await expect(page.getByTestId("compare-page-indicator")).toHaveText("Page 1 of 2");
  await expect(page.locator('[data-testid^="compare-card-"]')).toHaveCount(expectedPageSize);

  await page.getByTestId("compare-primary-watched").click();
  await expect(page.getByTestId("compare-page-indicator")).toHaveText("Page 1 of 2");
  await expect(page.getByText(/Alex liked it/)).toBeVisible();
  await expect(page.getByText(/You S1 E2/)).toBeVisible();
  await expect(page.getByText(/Alex S1 E4/)).toBeVisible();

  await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" }));
  await expectStableScroll(page, () => page.waitForTimeout(250), 8);
  await expectStableScroll(page, () => page.waitForTimeout(500), 8);

  await page.getByTestId("compare-primary-recs").evaluate((button) => button.click());
  await expect(page.getByTestId("compare-list-recs")).toBeVisible();
  await expect(page.getByTestId("compare-page-indicator")).toHaveText("Page 1 of 2");
  await page.getByTestId("compare-primary-watchlists").click();
  await page.getByTestId("compare-secondary-only_me").click();
  await expect(page.getByTestId("compare-page-indicator")).toHaveText("Page 1 of 2");
  await page.getByTestId("compare-secondary-only_them").click();
  await expect(page.getByTestId("compare-page-indicator")).toHaveText("Page 1 of 2");
});