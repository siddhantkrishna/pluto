import { test, expect } from "@playwright/test";
test("protected route redirects to login", async ({ page }) => {
  await page.goto("/workspaces");
  await expect(page).toHaveURL(/\/login/);
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
});
test("register, workspace, catalog CRUD, account and logout", async ({
  page,
}) => {
  const email = `browser-${Date.now()}@example.org`;
  const password = "Browser verification passphrase!";
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Browser Owner");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("status")).toContainText("account is ready");
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in →" }).click();
  await expect(page).toHaveURL("/workspaces");
  await page.getByRole("button", { name: "+ Create institution" }).click();
  await page
    .getByLabel("Institution name")
    .fill("Browser Verification Institute");
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Workspace overview" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Data catalog", exact: true }).click();
  await page.getByRole("button", { name: "+ Register dataset" }).click();
  await page.getByLabel("Dataset name").fill("Verified dataset");
  await page
    .getByLabel("Description", { exact: true })
    .fill("Metadata entered through the real application.");
  await page.getByRole("button", { name: "Save dataset metadata" }).click();
  await expect(
    page.getByRole("cell", { name: "Verified dataset local_file" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../.local/catalog-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../../.local/catalog-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Dataset name").fill("Updated dataset");
  await page.getByRole("button", { name: "Save dataset metadata" }).click();
  await expect(
    page.getByRole("cell", { name: "Updated dataset local_file" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No datasets found." }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Data sources", exact: true }).click();
  await page.getByRole("button", { name: "+ Define source" }).click();
  await page.getByLabel("Source name").fill("Future local source");
  await page.getByRole("button", { name: "Save source definition" }).click();
  await expect(page.getByText("Not configured", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Activity", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "dataset.created", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Account & security", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Active sessions" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
});
test("mobile landing and login have no horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /A foundation/ }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.goto("/login");
  await expect(page.getByLabel("Email address")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("resumable upload interface queues real content", async ({ page }) => {
  const email = `ingest-browser-${Date.now()}@example.org`,
    password = "Browser verification passphrase!";
  const headers = { Origin: "http://localhost:3000" };
  await page.request.post("/api/v1/auth/register", {
    headers,
    data: { name: "Ingestion Test", email, password },
  });
  const login = await page.request.post("/api/v1/auth/login", {
    headers,
    data: { email, password },
  });
  const me = await login.json();
  const authenticated = { ...headers, "X-CSRF-Token": me.csrf };
  const org = await (
    await page.request.post("/api/v1/institutions", {
      headers: authenticated,
      data: { name: "Ingestion Verification Institute" },
    })
  ).json();
  await page.request.post(`/api/v1/catalog/${org.id}`, {
    headers: authenticated,
    data: {
      name: "Upload verification",
      source_category: "local_file",
      owner_id: me.user.id,
    },
  });
  await page.goto(`/workspace/${org.id}/imports`);
  await expect(
    page.getByRole("option", { name: "Upload verification" }).first(),
  ).toBeAttached();
  await page.getByLabel("Choose or drop a file").setInputFiles({
    name: "test.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Verified institutional text"),
  });
  await expect(
    page.getByRole("option", { name: "Upload verification" }).first(),
  ).toBeAttached();
  await page.getByRole("button", { name: "Upload / resume" }).click();
  await expect(
    page.getByRole("cell", { name: "queued", exact: true }),
  ).toBeVisible();
});
