import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, test, vi } from 'vitest';
import App from './App';

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
    review_text: '배달이 1시간 넘게 걸렸어요.',
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

function jsonResponse(body, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
}

function mockApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input, options = {}) => {
      const url = new URL(String(input));
      const path = url.pathname.replace('/api/v1', '');
      const method = options.method || 'GET';

      if (method === 'POST' && path === '/stores') return jsonResponse(store, 201);
      if (method === 'GET' && path === '/stores/1') return jsonResponse(store);
      if (method === 'GET' && path === '/stores/1/reviews/stats') return jsonResponse(stats);
      if (method === 'GET' && path === '/stores/1/reviews') {
        return jsonResponse({ total: reviews.length, page: 1, size: 50, reviews });
      }
      if (method === 'GET' && path === '/stores/1/reviews/1') return jsonResponse(reviews[0]);
      if (method === 'GET' && path === '/stores/1/reviews/2') return jsonResponse(reviews[1]);
      if (method === 'POST' && path === '/stores/1/reviews/analyze') {
        return jsonResponse({
          task_id: 'task_test',
          message: '분석이 시작되었습니다. WebSocket으로 진행 상황을 확인하세요.',
          total: 2,
        }, 202);
      }
      return jsonResponse({ detail: 'not found' }, 404);
    }),
  );
}

function mockOfflineApi() {
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('offline'))));
}

describe('Review helper SPA', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, '', '/');
  });

  test('setup validates required store name', async () => {
    mockApi();
    window.history.pushState({}, '', '/setup');
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole('button', { name: '등록' }));

    expect(screen.getByRole('alert')).toHaveTextContent('가게 이름을 입력해 주세요.');
  });

  test('setup shows backend connection error when API is offline', async () => {
    mockOfflineApi();
    window.history.pushState({}, '', '/setup');
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole('button', { name: '데모 채우기' }));
    await user.click(screen.getByRole('button', { name: '등록' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('백엔드 서버에 연결할 수 없습니다');
    expect(window.location.pathname).toBe('/setup');
    expect(localStorage.getItem('store_id')).toBeNull();
  });

  test('setup saves store through API and routes to dashboard', async () => {
    mockApi();
    window.history.pushState({}, '', '/setup');
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole('button', { name: '데모 채우기' }));
    await user.click(screen.getByRole('button', { name: '등록' }));

    expect(await screen.findByRole('heading', { name: '민트치킨 성수점' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/dashboard');
    expect(localStorage.getItem('store_id')).toBe('1');
  });

  test('dashboard can select visible reviews and request batch analysis', async () => {
    mockApi();
    localStorage.setItem('store_id', '1');
    window.history.pushState({}, '', '/dashboard');
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole('heading', { name: '민트치킨 성수점' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /전체 선택/ }));
    await user.click(screen.getByRole('button', { name: /분석 시작/ }));

    await waitFor(() => {
      expect(screen.getByText('분석이 시작되었습니다. WebSocket으로 진행 상황을 확인하세요.')).toBeInTheDocument();
    });
  });
});
