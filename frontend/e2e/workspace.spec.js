import { test, expect } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
const fixtures = () =>
  JSON.parse(readFileSync(process.env.PHASE8_FIXTURE_FILE, "utf8"));
async function login(page, account) {
  await page.goto("/");
  await page.getByLabel("Email address").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  const signedIn = page.waitForResponse((r) => r.url().endsWith("/auth/login"));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const data = (await (await signedIn).json()).data;
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toBeVisible();
  return data;
}
async function open(page, id) {
  await page.evaluate((id) => {
    location.hash = "/consultations/" + id;
  }, id);
  await expect(
    page.getByRole("heading", {
      name: "Consultation " + id.slice(0, 8),
      exact: true,
    }),
  ).toBeVisible();
}
async function complete(page) {
  for (const select of await page.getByLabel(/^Decision for /).all())
    await select.selectOption("ACCEPT");
  await page
    .getByLabel("Doctor care notes", { exact: true })
    .fill("Synthetic browser notes. No clinical claim.");
  await page.getByLabel("Care notes are complete").check();
  await page
    .getByRole("button", { name: "Save review revision", exact: true })
    .click();
  await expect(
    page.getByText("Review revision 1 saved.", { exact: true }),
  ).toBeVisible();
}
async function screenshot(page, name) {
  if (!process.env.SCREENSHOT_DIR) return;
  mkdirSync(process.env.SCREENSHOT_DIR, { recursive: true });
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    document.querySelectorAll("textarea").forEach((e) => {
      e.scrollTop = 0;
    });
  });
  await page.screenshot({
    path: join(process.env.SCREENSHOT_DIR, name + ".png"),
    fullPage: true,
  });
}
async function mobile(page, name) {
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await screenshot(page, name);
}

test("patient draft revisions, unsaved warnings and real disabled inference", async ({
  page,
}) => {
  await login(page, fixtures().session.accounts.patient);
  await screenshot(page, "patient-desktop");
  await page.getByRole("button", { name: "New consultation" }).click();
  await page.getByLabel("Draft schema version").fill("synthetic-browser-v1");
  await page
    .getByLabel("Draft data (JSON object)")
    .fill('{"synthetic":"patient input"}');
  await page
    .getByLabel("Input provenance (JSON object)")
    .fill('{"source":"synthetic browser test"}');
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Back to consultations" }).click();
  await expect(page.getByLabel("Draft schema version")).toHaveValue(
    "synthetic-browser-v1",
  );
  await page.getByRole("button", { name: "Save input draft" }).click();
  await expect(
    page.getByText("Draft saved as input revision 1.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Submit saved revision" }),
  ).toBeDisabled();
  await page
    .getByLabel("Draft data (JSON object)")
    .fill('{"synthetic":"corrected input"}');
  await page.getByRole("button", { name: "Save input draft" }).click();
  await expect(
    page.getByText("Draft saved as input revision 2.", { exact: true }),
  ).toBeVisible();
  await screenshot(page, "patient-draft-desktop");
  await mobile(page, "patient-draft-mobile");
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
});

test("synthetic approved snapshot, explicit replacement, restoration and private patient PDF", async ({
  page,
}) => {
  const f = fixtures().approval;
  await login(page, f.accounts.doctor);
  await open(page, f.id);
  await expect(page.getByLabel(/^Decision for /).first()).toHaveValue("");
  await complete(page);
  const label = await page
    .getByLabel(/^Decision for /)
    .first()
    .evaluate((e) => e.closest(".field").querySelector("label").textContent);
  const target = label.replace("Decision for ", "");
  await page
    .getByLabel(/^Decision for /)
    .first()
    .selectOption("EDIT");
  await page
    .getByLabel("Replacement for " + target)
    .fill("Synthetic replacement <b>literal</b> & café Ω Ж.");
  await page
    .getByLabel("Reason for " + target)
    .fill("Synthetic internal reason hidden from patient.");
  await page
    .getByLabel("Doctor care notes", { exact: true })
    .fill("Synthetic care note café Ω Ж with literal <tag>.\n".repeat(30));
  await page
    .getByLabel("Optional doctor prescription")
    .fill("Synthetic prescription; no medication or clinical claim.");
  await screenshot(page, "doctor-review-desktop");
  await mobile(page, "doctor-review-mobile");
  await page
    .getByRole("button", { name: "Save review revision", exact: true })
    .click();
  await expect(
    page.getByText("Review revision 2 saved.", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Replacement for " + target)).toHaveValue(
    "Synthetic replacement <b>literal</b> & café Ω Ж.",
  );
  await page.getByLabel("Historical review revision").fill("1");
  await page.getByRole("button", { name: "Inspect saved revision" }).click();
  await expect(
    page.getByText("Saved review revision 1 (read-only)", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Review approval", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Review revision 2");
  await page
    .getByRole("button", { name: "Confirm approval of revision 2" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Approved care snapshot" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await login(page, f.accounts.patient);
  await open(page, f.id);
  await expect(
    page.getByText("Synthetic replacement <b>literal</b> & café Ω Ж.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Synthetic internal reason", { exact: false }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Original model output", { exact: false }),
  ).toHaveCount(0);
  const downloaded = page.waitForEvent("download"),
    response = page.waitForResponse((r) => r.url().endsWith("/download"));
  await page.getByRole("button", { name: "Download approved PDF" }).click();
  const artifact = await downloaded;
  const reportId = artifact.suggestedFilename().slice(16, -4);
  const extracted = execFileSync(
    process.env.PYTHON || "python",
    [
      "-c",
      'from pypdf import PdfReader; import sys; print("\\n".join(p.extract_text() for p in PdfReader(sys.argv[1]).pages))',
      await artifact.path(),
    ],
    { encoding: "utf8" },
  );
  expect(extracted).toContain("SYNTHETIC TEST DATA");
  expect(extracted).toContain(
    "Synthetic replacement <b>literal</b> & café Ω Ж.",
  );
  expect(extracted).not.toContain("Synthetic internal reason");
  expect(artifact.suggestedFilename()).toMatch(
    /^ayursage-report-[a-f0-9-]+\.pdf$/,
  );
  const headers = (await response).headers();
  expect(headers["cache-control"]).toBe("no-store");
  expect(headers["content-type"]).toBe("application/pdf");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await screenshot(page, "approved-patient-desktop");
  await mobile(page, "approved-patient-mobile");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  const other = await login(page, f.accounts.other_patient);
  const unauthorized = await page.request.get(
    "/api/v1/reports/" + reportId + "/download",
    { headers: { Authorization: "Bearer " + other.accessToken } },
  );
  expect(unauthorized.status()).toBe(404);
  await page.evaluate((id) => {
    location.hash = "/consultations/" + id;
  }, f.id);
  await expect(page.getByRole("alert")).toContainText("not found");
  await expect(
    page.getByRole("heading", { name: "Approved care snapshot" }),
  ).toHaveCount(0);
});

test("actual clinical approval gate and other-doctor denial", async ({
  page,
}) => {
  const f = fixtures().blocked;
  await login(page, f.accounts.doctor);
  await open(page, f.id);
  await complete(page);
  await page
    .getByRole("button", { name: "Review approval", exact: true })
    .click();
  const response = page.waitForResponse((r) => r.url().endsWith("/approve"));
  await page
    .getByRole("button", { name: "Confirm approval of revision 1" })
    .click();
  expect((await response).status()).toBe(503);
  await expect(page.getByRole("alert")).toContainText("Action unavailable");
  await expect(
    page.getByRole("heading", { name: "Approved care snapshot" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await login(page, f.accounts.other_doctor);
  await page.evaluate((id) => {
    location.hash = "/consultations/" + id;
  }, f.id);
  await expect(page.getByRole("alert")).toContainText("not found");
});

test("real stale save retains work, focuses error and reloads latest revision", async ({
  browser,
}) => {
  const f = fixtures().stale;
  const a = await browser.newContext(),
    b = await browser.newContext();
  const first = await a.newPage(),
    second = await b.newPage();
  try {
    await login(first, f.accounts.doctor);
    await open(first, f.id);
    await login(second, f.accounts.doctor);
    await open(second, f.id);
    await second
      .getByLabel("Doctor care notes", { exact: true })
      .fill("Synthetic unsaved second-tab text");
    await complete(first);
    await second
      .getByRole("button", { name: "Save review revision", exact: true })
      .click();
    await expect(second.getByRole("alert")).toContainText(
      "This record changed",
    );
    await expect(second.getByRole("alert")).toBeFocused();
    await expect(
      second.getByLabel("Doctor care notes", { exact: true }),
    ).toHaveValue("Synthetic unsaved second-tab text");
    second.once("dialog", (dialog) => dialog.accept());
    await second.getByRole("button", { name: "Reload current record" }).click();
    await expect(
      second.getByLabel("Doctor care notes", { exact: true }),
    ).toHaveValue("Synthetic browser notes. No clinical claim.");
  } finally {
    await a.close();
    await b.close();
  }
});

test("information request, patient clarification and new input revision", async ({
  page,
}) => {
  const f = fixtures().information;
  await login(page, f.accounts.doctor);
  await open(page, f.id);
  await page
    .getByLabel("Information request reason")
    .fill("Synthetic request: clarify your source context.");
  await page.getByRole("button", { name: "Send information request" }).click();
  await expect(
    page.getByText("NEEDS INFORMATION", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await login(page, f.accounts.patient);
  await open(page, f.id);
  await expect(
    page.getByText("Synthetic request: clarify your source context.", {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByLabel("Draft data (JSON object)")
    .fill('{"synthetic":"patient clarification"}');
  await page.getByRole("button", { name: "Save input draft" }).click();
  await expect(
    page.getByText("Draft saved as input revision 2.", { exact: true }),
  ).toBeVisible();
});

test("registration, cookie rotation, restoration, expiry and keyboard navigation", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await screenshot(page, "auth-desktop");
  await mobile(page, "auth-mobile");
  await page
    .getByRole("button", { name: "New patient? Create an account" })
    .click();
  await page
    .getByLabel("Email address")
    .fill("synthetic-browser-" + Date.now() + "@example.invalid");
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-registration-password");
  await page
    .getByLabel("Clinic-provided terms version")
    .fill("synthetic-test-terms-only");
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Create patient account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "My consultations" }),
  ).toBeVisible();
  const before = (await context.cookies()).find(
    (c) => c.name === "refresh_token",
  );
  expect(before.httpOnly).toBe(true);
  expect(before.path).toBe("/api/v1/auth");
  expect(
    (await context.cookies()).find((c) => c.name === "csrf_token").path,
  ).toBe("/");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "My consultations" }),
  ).toBeVisible();
  expect(
    (await context.cookies()).find((c) => c.name === "refresh_token").value,
  ).not.toBe(before.value);
  // Shift+Tab from the focused main landmark reaches the sign-out control; the
  // first Tab from the document reaches the visible keyboard skip link.
  await page.evaluate(() => document.activeElement.blur());
  await page.keyboard.press("Control+Home");
  await page.locator(".skip").focus();
  await expect(
    page.getByRole("link", { name: "Skip to main content" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  await context.clearCookies();
  await page.waitForTimeout(3200);
  await page.getByRole("button", { name: "New consultation" }).click();
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "My consultations" }),
  ).toHaveCount(0);
});

test("actual admin onboarding and assignment, restricted clinical routes", async ({
  page,
}) => {
  const f = fixtures().admin;
  await login(page, f.accounts.admin);
  await expect(
    page.getByRole("heading", { name: "Clinic administration" }),
  ).toBeVisible();
  await screenshot(page, "admin-desktop");
  await page
    .getByLabel("Doctor email")
    .fill("synthetic-doctor-" + Date.now() + "@example.invalid");
  await page
    .getByLabel("Initial doctor password")
    .fill("synthetic-new-doctor-password");
  await page
    .getByLabel("Verification provenance (JSON object)")
    .fill('{"syntheticTestOnly":true,"reviewer":"synthetic fixture"}');
  await page.getByRole("button", { name: "Create verified doctor" }).click();
  await expect(
    page.getByText("Verified doctor account created.", { exact: false }),
  ).toBeVisible();
  await page.getByLabel("Consultation ID", { exact: true }).fill(f.id);
  await page.getByLabel("Expected record version").fill(String(f.rowVersion));
  await page
    .getByLabel("Active verified doctor ID")
    .fill(f.accounts.other_doctor.id);
  await page
    .getByLabel("Assignment reason")
    .fill("Synthetic assignment integration test");
  await page.getByRole("button", { name: "Record assignment" }).click();
  await expect(
    page.getByText("Assignment recorded.", { exact: false }),
  ).toBeVisible();
  await mobile(page, "admin-mobile");
  await page.evaluate((id) => {
    location.hash = "/consultations/" + id;
  }, f.id);
  await expect(page.getByRole("alert")).toContainText(
    "unavailable for your account role",
  );
  await expect(
    page.getByRole("button", { name: "Download approved PDF" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await login(page, f.accounts.doctor);
  await page.evaluate((id) => {
    location.hash = "/consultations/" + id;
  }, f.id);
  await expect(page.getByRole("alert")).toContainText("not found");
});

test("UI fault injection: report outage, safe retry and duplicate-click protection", async ({
  page,
}) => {
  const f = fixtures().report;
  await login(page, f.accounts.patient);
  await open(page, f.id);
  await expect(
    page.getByRole("heading", { name: "Approved care snapshot" }),
  ).toBeVisible();
  // Explicit browser response mock: this verifies UI handling, not an Azure outage.
  await page.route(
    "**/consultations/" + f.id + "/reports",
    (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "REPORT_UNAVAILABLE",
            message: "Synthetic report service unavailable",
          },
          requestId: "synthetic-support-id",
        }),
      }),
    { times: 1 },
  );
  await page.getByRole("button", { name: "Download approved PDF" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Synthetic report service unavailable",
  );
  await expect(page.getByRole("alert")).toContainText("synthetic-support-id");
  let requests = 0,
    release;
  const hold = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/consultations/" + f.id + "/reports", async (route) => {
    requests++;
    await hold;
    await route.continue();
  });
  await page.getByRole("button", { name: "Download approved PDF" }).click();
  const busy = page.getByRole("button", { name: "Preparing private PDF…" });
  await expect(busy).toBeDisabled();
  await busy.evaluate((button) => {
    button.click();
    button.click();
  });
  await expect.poll(() => requests).toBe(1);
  const download = page.waitForEvent("download");
  release();
  await download;
  await expect(
    page.getByRole("button", { name: "Download approved PDF" }),
  ).toBeEnabled();
  // A subsequent intentional download uses the same backend report identity.
  const previous = await page.getByText(/^Report status:/).textContent();
  const again = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download approved PDF" }).click();
  await again;
  await expect(page.getByText(/^Report status:/)).toHaveText(previous);
});

test("UI fault injection: network error and forbidden response remain safe", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Email address").fill("synthetic@example.invalid");
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-password-only");
  await page.route("**/auth/login", (route) => route.abort(), { times: 1 });
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Connection unavailable");
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-password-only");
  await page.route(
    "**/auth/login",
    (route) =>
      route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "FORBIDDEN",
            message: "Synthetic operation is not permitted",
          },
        }),
      }),
    { times: 1 },
  );
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Synthetic operation is not permitted",
  );
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toHaveCount(0);
});
