const { test, expect } = require('@playwright/test');

test.describe('Auth Flow', () => {
  test('signup flow - new user redirected to onboarding', async ({ page }) => {
    // Mock signup API
    await page.route('**/api/auth/register', async route => {
      await route.fulfill({
        status: 200,
        json: { token: 'mock-token', user: { id: 1, email: 'test@example.com', isOnboarded: false } }
      });
    });

    await page.goto('/signup');
    await page.fill('[data-testid="register-name-input"]', 'Test User');
    await page.fill('[data-testid="register-email-input"]', 'test@example.com');
    await page.fill('[data-testid="register-password-input"]', 'Password123!');
    await page.fill('[data-testid="register-password-confirm-input"]', 'Password123!');
    await page.click('[data-testid="register-submit-button"]');

    // Should redirect to onboarding
    await expect(page).toHaveURL(/.*\/onboarding/);
  });

  test('login flow - valid credentials redirect to dashboard', async ({ page }) => {
    await page.route('**/api/auth/login', async route => {
      await route.fulfill({
        status: 200,
        json: { token: 'mock-token', user: { id: 1, email: 'test@example.com', isOnboarded: true } }
      });
    });

    await page.goto('/login');
    await page.fill('[data-testid="login-email-input"]', 'test@example.com');
    await page.fill('[data-testid="login-password-input"]', 'Password123!');
    await page.click('[data-testid="login-submit-button"]');

    // Should redirect to dashboard since user isOnboarded
    await expect(page).toHaveURL(/.*\/dashboard/);
  });

  test('login flow - invalid credentials show error', async ({ page }) => {
    await page.route('**/api/auth/login', async route => {
      await route.fulfill({
        status: 401,
        json: { message: 'Invalid credentials' }
      });
    });

    await page.goto('/login');
    await page.fill('[data-testid="login-email-input"]', 'wrong@example.com');
    await page.fill('[data-testid="login-password-input"]', 'wrongpass');
    await page.click('[data-testid="login-submit-button"]');

    // Error should be visible, staying on login page
    const errorToast = page.locator('text=Invalid credentials');
    await expect(errorToast).toBeVisible();
    await expect(page).toHaveURL(/.*\/login/);
  });

  test('logout flow - redirected to login', async ({ page }) => {
    // Setup initial state as logged in
    await page.route('**/api/auth/login', async route => {
      await route.fulfill({
        status: 200,
        json: { token: 'mock-token', user: { id: 1, email: 'test@example.com', isOnboarded: true } }
      });
    });

    await page.goto('/login');
    await page.fill('[data-testid="login-email-input"]', 'test@example.com');
    await page.fill('[data-testid="login-password-input"]', 'Password123!');
    await page.click('[data-testid="login-submit-button"]');
    await expect(page).toHaveURL(/.*\/dashboard/);

    // Click logout
    await page.click('[data-testid="logout-button"]');
    await expect(page).toHaveURL(/.*\/login/);
  });

  test('protected route - unauthenticated redirected to login', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/.*\/login/);
  });

  test('admin route - non-admin redirected to dashboard', async ({ page }) => {
    // Mock user login as non-admin
    await page.route('**/api/auth/me', async route => {
      await route.fulfill({
        status: 200,
        json: { user: { id: 1, email: 'test@example.com', role: 'user', isOnboarded: true } }
      });
    });

    // Mock initial local storage or auth context state
    await page.addInitScript(() => {
      window.localStorage.setItem('token', 'mock-token');
    });

    await page.goto('/admin');
    await expect(page).toHaveURL(/.*\/dashboard/);
  });
});
