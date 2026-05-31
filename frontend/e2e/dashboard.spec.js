import { expect, test } from '@playwright/test';

const consoleErrors = new WeakMap();

test.beforeEach(async ({ page }) => {
  const errors = [];
  consoleErrors.set(page, errors);
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', (error) => {
    errors.push(error.message);
  });

  await page.goto('/setup');
  await page.evaluate(() => localStorage.clear());
});

test.afterEach(async ({ page }) => {
  expect(consoleErrors.get(page) || []).toEqual([]);
});

test('setup to dashboard flow works', async ({ page }) => {
  await page.goto('/setup');
  await page.getByRole('button', { name: '데모 채우기' }).click();
  await page.getByRole('button', { name: '등록' }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: '민트치킨 성수점' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '리뷰 목록' })).toBeVisible();
  await expect(page.getByText('승인필요').first()).toBeVisible();
});

test('dashboard batch and approval controls are usable', async ({ page }) => {
  await page.evaluate(() => localStorage.setItem('store_id', '1'));
  await page.goto('/dashboard');

  await expect(page.getByRole('heading', { name: '민트치킨 성수점' })).toBeVisible();
  await page.getByRole('button', { name: /전체 선택/ }).click();
  await page.getByRole('button', { name: /답변 생성/ }).click();
  await expect(page.getByText('답변 생성이 완료되었습니다.')).toBeVisible();

  await page.getByText('기다림끝').click();
  await page.getByRole('button', { name: '승인', exact: true }).click();
  await expect(page.getByText('답변이 승인되었습니다.')).toBeVisible();
});
