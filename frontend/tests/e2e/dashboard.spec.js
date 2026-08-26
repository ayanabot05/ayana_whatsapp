const { test, expect } = require('@playwright/test');

test.describe('Dashboard Tabs', () => {
  test.beforeEach(async ({ page }) => {
    // Mock logged in user
    await page.addInitScript(() => {
      window.localStorage.setItem('token', 'mock-token');
    });
    await page.route('**/api/auth/me', async route => {
      await route.fulfill({
        status: 200,
        json: { user: { id: 1, email: 'test@example.com', isOnboarded: true, phoneVerified: true } }
      });
    });
    
    // Default mock for generic data fetching
    await page.route('**/api/dashboard/**', async route => {
      await route.fulfill({ status: 200, json: { data: [] } });
    });

    await page.goto('/dashboard');
  });

  test('tab navigation between all 7 tabs', async ({ page }) => {
    const tabs = ['Overview', 'Parents', 'Check-ins', 'Care Circle', 'Settings', 'Account', 'Help']; // Adjust names as necessary

    for (const tab of tabs) {
      await page.click(`button[role="tab"]:has-text("${tab}")`);
      // Assert the tab content is visible (could check a specific heading inside)
      await expect(page.locator(`[role="tabpanel"]`)).toBeVisible();
    }
  });

  test('parents tab - edit parent details', async ({ page }) => {
    await page.route('**/api/parents', async route => {
      await route.fulfill({
        status: 200,
        json: [{ id: 1, name: 'Alice', relationship: 'Mother' }]
      });
    });
    await page.click('button[role="tab"]:has-text("Parents")');
    
    await page.click('button:has-text("Edit")');
    await page.fill('input[name="parentName"]', 'Alice Updated');
    
    await page.route('**/api/parents/1', async route => {
      await route.fulfill({ status: 200, json: { success: true } });
    });
    await page.click('button:has-text("Save")');
    
    await expect(page.locator('text="Alice Updated"')).toBeVisible();
  });

  test('parents tab - send test message', async ({ page }) => {
    await page.click('button[role="tab"]:has-text("Parents")');
    
    await page.route('**/api/parents/test-message', async route => {
      await route.fulfill({ status: 200, json: { success: true } });
    });
    
    await page.click('button:has-text("Send Test Message")');
    
    // Expect success toast
    await expect(page.locator('text=Message sent successfully')).toBeVisible();
  });

  test('checkins tab - view activity timeline', async ({ page }) => {
    await page.route('**/api/checkins/timeline', async route => {
      await route.fulfill({
        status: 200,
        json: [{ id: 1, date: '2023-01-01', status: 'Completed' }]
      });
    });
    
    await page.click('button[role="tab"]:has-text("Check-ins")');
    await expect(page.locator('text="Completed"')).toBeVisible();
  });

  test('care circle tab - invite member', async ({ page }) => {
    await page.click('button[role="tab"]:has-text("Care Circle")');
    
    await page.click('button:has-text("Invite Member")');
    await page.fill('input[name="email"]', 'invitee@example.com');
    
    await page.route('**/api/care-circle/invite', async route => {
      await route.fulfill({ status: 200, json: { success: true } });
    });
    
    await page.click('button:has-text("Send Invite")');
    await expect(page.locator('text=Invite sent')).toBeVisible();
  });

  test('account tab - shows phone verification', async ({ page }) => {
    await page.click('button[role="tab"]:has-text("Account")');
    await expect(page.locator('text=Phone Verified')).toBeVisible();
  });

  test('account tab - delete account confirmation', async ({ page }) => {
    await page.click('button[role="tab"]:has-text("Account")');
    await page.click('button:has-text("Delete Account")');
    
    const dialog = page.locator('dialog, [role="dialog"]');
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('Are you sure');
    
    await page.route('**/api/account', async (route, request) => {
      if (request.method() === 'DELETE') {
        await route.fulfill({ status: 200, json: { success: true } });
      }
    });
    
    await dialog.locator('button:has-text("Confirm")').click();
    await expect(page).toHaveURL(/.*\/login|\//);
  });
});
