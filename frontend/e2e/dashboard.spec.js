import { expect, test } from '@playwright/test';

const consoleErrors = new WeakMap();
const allowNetworkConsoleErrors = new WeakMap();

const store = {
  id: 1,
  store_name: '민트치킨 성수점',
  origin_info: '닭고기: 국내산',
  is_dine_in: true,
  is_takeout: true,
  is_delivery: true,
  created_at: '2026-05-31T10:00:00',
};

const reviews = [
  {
    id: 1,
    store_id: 1,
    review_text: '치킨이 정말 바삭하고 소스도 넉넉했어요.',
    reviewer_name: '바삭러버',
    rating: 5,
    order_type: 'delivery',
    sentiment: 'positive',
    sub_type: null,
    risk_level: 'low',
    interpretation: {
      core_issue: '음식 품질 만족',
      action_direction: '감사 인사',
      reply_tone: '감사',
    },
    reply_text: '감사합니다.',
    status: 'auto_replied',
    rag_references: [],
    created_at: '2026-05-31T11:20:00',
    updated_at: '2026-05-31T11:24:00',
  },
  {
    id: 2,
    store_id: 1,
    review_text: '배달이 1시간 넘게 걸렸고 도착했을 때 감자가 너무 식어 있었어요.',
    reviewer_name: '기다림끝',
    rating: 2,
    order_type: 'delivery',
    sentiment: 'negative',
    sub_type: '배달지연',
    risk_level: 'medium',
    interpretation: {
      core_issue: '배달 지연',
      action_direction: '사과와 개선',
      reply_tone: '사과',
    },
    reply_text: '불편을 드려 죄송합니다.',
    status: 'needs_approval',
    rag_references: [],
    created_at: '2026-05-31T12:05:00',
    updated_at: '2026-05-31T12:16:00',
  },
];

const stats = {
  total_reviews: 2,
  sentiment_distribution: { positive: 1, negative: 1, malicious: 0 },
  risk_distribution: { low: 1, medium: 1, high: 0 },
  status_distribution: {
    pending: 0,
    analyzing: 0,
    analyzed: 0,
    generating: 0,
    auto_replied: 1,
    needs_approval: 1,
    approved: 0,
    on_hold: 0,
  },
  sub_type_distribution: { 배달지연: 1 },
};

async function mockBackend(page) {
  await page.route('http://localhost:8000/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/v1', '');
    const method = request.method();

    if (method === 'POST' && path === '/stores') {
      await route.fulfill({ status: 201, json: store });
      return;
    }
    if (method === 'GET' && path === '/stores/1') {
      await route.fulfill({ json: store });
      return;
    }
    if (method === 'GET' && path === '/stores/1/reviews/stats') {
      await route.fulfill({ json: stats });
      return;
    }
    if (method === 'GET' && path === '/stores/1/reviews') {
      const size = Number(url.searchParams.get('size') || '20');
      if (size > 100) {
        await route.fulfill({
          status: 422,
          json: {
            detail: [
              {
                loc: ['query', 'size'],
                msg: 'Input should be less than or equal to 100',
                type: 'less_than_equal',
              },
            ],
          },
        });
        return;
      }
      await route.fulfill({ json: { total: reviews.length, page: 1, size, reviews } });
      return;
    }
    if (method === 'GET' && path === '/stores/1/reviews/1') {
      await route.fulfill({ json: reviews[0] });
      return;
    }
    if (method === 'GET' && path === '/stores/1/reviews/2') {
      await route.fulfill({ json: reviews[1] });
      return;
    }
    if (method === 'POST' && path === '/stores/1/reviews/generate-replies') {
      await route.fulfill({
        status: 202,
        json: {
          task_id: 'task_generation',
          message: '답변 생성이 시작되었습니다. WebSocket으로 진행 상황을 확인하세요.',
          total: 2,
        },
      });
      return;
    }
    if (method === 'POST' && path === '/stores/1/reviews/2/approve') {
      await route.fulfill({
        json: { id: 2, status: 'approved', message: '답변이 승인되었습니다.' },
      });
      return;
    }

    await route.fulfill({ status: 404, json: { detail: 'not found' } });
  });
}

test.beforeEach(async ({ page }) => {
  const errors = [];
  consoleErrors.set(page, errors);
  allowNetworkConsoleErrors.set(page, false);
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
  const errors = consoleErrors.get(page) || [];
  if (allowNetworkConsoleErrors.get(page)) {
    expect(errors.every((message) => message.includes('ERR_CONNECTION_REFUSED'))).toBe(true);
    return;
  }
  expect(errors).toEqual([]);
});

test('setup shows API error when backend is offline', async ({ page }) => {
  allowNetworkConsoleErrors.set(page, true);
  await page.route('http://localhost:8000/api/v1/**', (route) => route.abort('connectionrefused'));
  await page.goto('/setup');
  await page.getByRole('button', { name: '데모 채우기' }).click();
  await page.getByRole('button', { name: '등록' }).click();

  await expect(page.getByRole('alert')).toContainText('백엔드 서버에 연결할 수 없습니다');
  await expect(page).toHaveURL(/\/setup$/);
});

test('setup to dashboard flow works with API responses', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/setup');
  await page.getByRole('button', { name: '데모 채우기' }).click();
  await page.getByRole('button', { name: '등록' }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: '민트치킨 성수점' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '리뷰 목록' })).toBeVisible();
  await expect(page.getByText('승인필요').first()).toBeVisible();
});

test('dashboard batch and approval controls call backend APIs', async ({ page }) => {
  await mockBackend(page);
  await page.evaluate(() => localStorage.setItem('store_id', '3'));
  await page.goto('/dashboard');

  await expect(page.getByRole('heading', { name: '민트치킨 성수점' })).toBeVisible();
  await page.getByRole('button', { name: /전체 선택/ }).click();
  await page.getByRole('button', { name: /답변 생성/ }).click();
  await expect(page.getByText('답변 생성이 시작되었습니다. WebSocket으로 진행 상황을 확인하세요.')).toBeVisible();

  await page.getByText('기다림끝').click();
  await page.getByRole('button', { name: '승인', exact: true }).click();
  await expect(page.getByText('답변이 승인되었습니다.')).toBeVisible();
});
