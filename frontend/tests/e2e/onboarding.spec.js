const { test, expect } = require('@playwright/test');

test.describe('Onboarding Flow', () => {
  test.beforeEach(async ({ page }) => {
    // Mock logged-in state, user not onboarded
    await page.addInitScript(() => {
      window.localStorage.setItem('token', 'mock-token');
    });
    await page.route('**/api/auth/me', async route => {
      await route.fulfill({
        status: 200,
        json: { user: { id: 1, email: 'test@example.com', isOnboarded: false } }
      });
    });
    await page.goto('/onboarding');
  });

  test('complete 4-step onboarding wizard', async ({ page }) => {
    // Step 0
    await page.fill('input[name="childName"]', 'Alice');
    await page.fill('input[name="childPhone"]', '+1234567890');
    await page.fill('input[name="city"]', 'New York');
    await page.selectOption('select[name="timezone"]', 'America/New_York');
    await page.check('input[name="consent"]');
    await page.click('button:has-text("Next")');

    // Step 1: Select Plan
    await page.click('div:has-text("Nitya plan")');
    await page.click('button:has-text("Next")');

    // Step 2: Add Parent
    await page.fill('input[name="parentName"]', 'Bob');
    await page.selectOption('select[name="relationship"]', 'Father');
    await page.fill('input[name="parentPhone"]', '+0987654321');
    await page.selectOption('select[name="language"]', 'en');
    await page.click('button:has-text("Next")');

    // Step 3: Activate
    await page.route('**/api/onboarding/complete', async route => {
      await route.fulfill({ status: 200, json: { success: true } });
    });
    
    await page.click('button:has-text("Activate")');
    
    // Check if it redirects or shows success
    await expect(page).toHaveURL(/.*\/dashboard|\/activation/);
  });

  test('step validation - cannot proceed without required fields', async ({ page }) => {
    // Attempt to proceed without filling fields
    await page.click('button:has-text("Next")');
    
    // Expect some validation error or to stay on the same step
    const stepTitle = page.locator('h2');
    await expect(stepTitle).toContainText('Child Details'); // Assuming step 0 title
  });

  test('back button navigates to previous step', async ({ page }) => {
    // Fill step 0
    await page.fill('input[name="childName"]', 'Alice');
    await page.fill('input[name="childPhone"]', '+1234567890');
    await page.fill('input[name="city"]', 'New York');
    await page.selectOption('select[name="timezone"]', 'America/New_York');
    await page.check('input[name="consent"]');
    await page.click('button:has-text("Next")');

    // Assert we are on Step 1
    await expect(page.locator('text="Nitya plan"').first()).toBeVisible();

    // Go back
    await page.click('button:has-text("Back")');
    
    // Assert we are on Step 0 again
    await expect(page.locator('input[name="childName"]')).toHaveValue('Alice');
  });
});
