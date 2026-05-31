import { demoReviews, demoStore } from '../data/mockData';

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
export const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000';

const STORE_ID_KEY = 'store_id';
const DEMO_STORE_KEY = 'review_helper_demo_store';
const DEMO_REVIEWS_KEY = 'review_helper_demo_reviews';
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true';

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

const clone = (value) => JSON.parse(JSON.stringify(value));

const getJson = (key, fallback) => {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : clone(fallback);
  } catch {
    return clone(fallback);
  }
};

const setJson = (key, value) => {
  localStorage.setItem(key, JSON.stringify(value));
};

const shouldUseFallback = (error) =>
  error instanceof TypeError || error?.status === 404 || error?.status === 501;

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method || 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  if (!response.ok) {
    let message = `API 요청 실패 (${response.status})`;
    try {
      const data = await response.json();
      message = data.detail || data.message || message;
    } catch {
      // Keep the status-based message when the server returns no JSON body.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return null;
  return response.json();
}

async function withFallback(realCall, fallbackCall) {
  if (DEMO_MODE) return fallbackCall();

  try {
    return await realCall();
  } catch (error) {
    if (shouldUseFallback(error)) return fallbackCall();
    throw error;
  }
}

function readDemoStore() {
  const stored = getJson(DEMO_STORE_KEY, demoStore);
  return stored?.id ? stored : clone(demoStore);
}

function writeDemoStore(store) {
  const normalized = {
    ...readDemoStore(),
    ...store,
    id: store.id || Number(localStorage.getItem(STORE_ID_KEY)) || 1,
    created_at: store.created_at || new Date().toISOString(),
  };
  setJson(DEMO_STORE_KEY, normalized);
  localStorage.setItem(STORE_ID_KEY, String(normalized.id));
  return normalized;
}

function readDemoReviews() {
  const reviews = getJson(DEMO_REVIEWS_KEY, demoReviews);
  if (!Array.isArray(reviews) || reviews.length === 0) return clone(demoReviews);
  return reviews;
}

function writeDemoReviews(reviews) {
  setJson(DEMO_REVIEWS_KEY, reviews);
  return reviews;
}

function filterReviews(reviews, filters = {}) {
  const orderType = filters.order_type === 'all' ? undefined : filters.order_type;
  const status = filters.status === 'all' ? undefined : filters.status;
  const sentiment = filters.sentiment === 'all' ? undefined : filters.sentiment;

  return reviews.filter((review) => {
    if (orderType && review.order_type !== orderType) return false;
    if (status && review.status !== status) return false;
    if (sentiment && review.sentiment !== sentiment) return false;
    return true;
  });
}

function countBy(items, key, keys) {
  const initial = Object.fromEntries(keys.map((item) => [item, 0]));
  return items.reduce((acc, item) => {
    const value = item[key];
    if (value) acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, initial);
}

function makeStats(reviews, orderType) {
  const scoped = filterReviews(reviews, { order_type: orderType });
  const subTypes = scoped.reduce((acc, review) => {
    if (review.sub_type) acc[review.sub_type] = (acc[review.sub_type] || 0) + 1;
    return acc;
  }, {});

  return {
    total_reviews: scoped.length,
    sentiment_distribution: countBy(scoped, 'sentiment', [
      'positive',
      'negative',
      'malicious',
    ]),
    risk_distribution: countBy(scoped, 'risk_level', ['low', 'medium', 'high']),
    status_distribution: countBy(scoped, 'status', [
      'pending',
      'analyzing',
      'analyzed',
      'generating',
      'auto_replied',
      'needs_approval',
      'approved',
      'on_hold',
    ]),
    sub_type_distribution: subTypes,
  };
}

function generatedReply(review) {
  if (review.sentiment === 'positive') {
    return `안녕하세요, ${readDemoStore().store_name}입니다. 남겨주신 따뜻한 리뷰 감사합니다. 좋게 봐주신 부분을 계속 지키며 다음 주문도 만족스럽게 준비하겠습니다.`;
  }

  if (review.sentiment === 'malicious') {
    return `안녕하세요, ${readDemoStore().store_name}입니다. 만족을 드리지 못한 점은 아쉽게 생각합니다. 정확한 확인을 위해 주문 내용과 불편하셨던 부분을 알려주시면 차분히 확인해 안내드리겠습니다.`;
  }

  return `안녕하세요, ${readDemoStore().store_name}입니다. 이용 중 불편을 드려 죄송합니다. 말씀해주신 ${review.sub_type || '내용'} 부분을 매장에서 확인하고 같은 문제가 반복되지 않도록 조리와 응대 과정을 점검하겠습니다.`;
}

function applyPrediction(review) {
  const prediction =
    review.mock_prediction || {
      sentiment: review.rating >= 4 ? 'positive' : 'negative',
      sub_type: review.rating >= 4 ? null : '기타',
      risk_level: review.rating >= 4 ? 'low' : 'medium',
      interpretation: {
        core_issue: review.rating >= 4 ? '만족 리뷰' : '개선 필요 리뷰',
        action_direction: review.rating >= 4 ? '감사 표현' : '사과와 개선 약속',
        reply_tone: review.rating >= 4 ? '감사' : '사과',
      },
    };

  return {
    ...review,
    sentiment: prediction.sentiment,
    sub_type: prediction.sub_type,
    risk_level: prediction.risk_level,
    interpretation: prediction.interpretation,
    reply_tone: prediction.interpretation?.reply_tone || review.reply_tone,
    status: 'analyzed',
    updated_at: new Date().toISOString(),
  };
}

function applyReply(review, forceRegenerated = false) {
  const next = {
    ...review,
    reply_text: forceRegenerated
      ? `${generatedReply(review)} 추가로, 남겨주신 의견은 오늘 마감 전 점검 항목에 반영하겠습니다.`
      : review.reply_text || generatedReply(review),
    status:
      review.risk_level === 'low' && review.sentiment === 'positive'
        ? 'auto_replied'
        : 'needs_approval',
    rag_references:
      review.rag_references?.length > 0
        ? review.rag_references
        : [
            {
              review: '비슷한 불편 리뷰가 있었어요.',
              reply: '불편을 드려 죄송합니다. 매장 프로세스를 점검하겠습니다.',
              similarity: 0.84,
            },
          ],
    updated_at: new Date().toISOString(),
  };

  return next;
}

const demoApi = {
  createStore(payload) {
    return Promise.resolve(writeDemoStore(payload));
  },
  getStore() {
    return Promise.resolve(readDemoStore());
  },
  updateStore(_storeId, payload) {
    return Promise.resolve(writeDemoStore({ ...payload, id: Number(_storeId) }));
  },
  getReviews(_storeId, filters = {}) {
    const page = Number(filters.page || 1);
    const size = Number(filters.size || 30);
    const filtered = filterReviews(readDemoReviews(), filters);
    const start = (page - 1) * size;

    return Promise.resolve({
      total: filtered.length,
      page,
      size,
      reviews: filtered.slice(start, start + size),
    });
  },
  getReview(_storeId, reviewId) {
    const review = readDemoReviews().find((item) => item.id === Number(reviewId));
    if (!review) return Promise.reject(new ApiError('리뷰를 찾을 수 없습니다.', 404));
    return Promise.resolve(review);
  },
  getStats(_storeId, orderType) {
    return Promise.resolve(makeStats(readDemoReviews(), orderType));
  },
  analyzeReviews(_storeId, reviewIds) {
    const ids = reviewIds.map(Number);
    const reviews = writeDemoReviews(
      readDemoReviews().map((review) => (ids.includes(review.id) ? applyPrediction(review) : review)),
    );

    return Promise.resolve({
      task_id: `demo_analysis_${Date.now()}`,
      message: '분석이 완료되었습니다.',
      total: ids.length,
      reviews,
    });
  },
  generateReplies(_storeId, reviewIds) {
    const ids = reviewIds.map(Number);
    const reviews = writeDemoReviews(
      readDemoReviews().map((review) => {
        if (!ids.includes(review.id)) return review;
        const analyzed = review.sentiment ? review : applyPrediction(review);
        return applyReply(analyzed);
      }),
    );

    return Promise.resolve({
      task_id: `demo_generation_${Date.now()}`,
      message: '답변 생성이 완료되었습니다.',
      total: ids.length,
      reviews,
    });
  },
  approveReview(_storeId, reviewId) {
    let updated;
    writeDemoReviews(
      readDemoReviews().map((review) => {
        if (review.id !== Number(reviewId)) return review;
        updated = { ...review, status: 'approved', updated_at: new Date().toISOString() };
        return updated;
      }),
    );
    return Promise.resolve({
      id: Number(reviewId),
      status: 'approved',
      message: '답변이 승인되었습니다.',
      review: updated,
    });
  },
  rejectReview(_storeId, reviewId) {
    let updated;
    writeDemoReviews(
      readDemoReviews().map((review) => {
        if (review.id !== Number(reviewId)) return review;
        updated = { ...review, status: 'on_hold', updated_at: new Date().toISOString() };
        return updated;
      }),
    );
    return Promise.resolve({
      id: Number(reviewId),
      status: 'on_hold',
      message: '답변이 보류 처리되었습니다.',
      review: updated,
    });
  },
  regenerateReply(_storeId, reviewId) {
    let updated;
    writeDemoReviews(
      readDemoReviews().map((review) => {
        if (review.id !== Number(reviewId)) return review;
        const analyzed = review.sentiment ? review : applyPrediction(review);
        updated = applyReply(analyzed, true);
        return updated;
      }),
    );
    return Promise.resolve({
      task_id: `demo_regeneration_${Date.now()}`,
      message: '답변을 다시 생성했습니다.',
      review: updated,
    });
  },
};

export const storeIdStorage = {
  get() {
    return localStorage.getItem(STORE_ID_KEY);
  },
  set(value) {
    localStorage.setItem(STORE_ID_KEY, String(value));
  },
  clear() {
    localStorage.removeItem(STORE_ID_KEY);
  },
};

export const api = {
  createStore(payload) {
    return withFallback(
      () => request('/stores', { method: 'POST', body: payload }),
      () => demoApi.createStore(payload),
    );
  },
  getStore(storeId) {
    return withFallback(
      () => request(`/stores/${storeId}`),
      () => demoApi.getStore(storeId),
    );
  },
  updateStore(storeId, payload) {
    return withFallback(
      () => request(`/stores/${storeId}`, { method: 'PUT', body: payload }),
      () => demoApi.updateStore(storeId, payload),
    );
  },
  getReviews(storeId, filters = {}) {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value && value !== 'all') params.set(key, value);
    });
    const query = params.toString() ? `?${params.toString()}` : '';

    return withFallback(
      () => request(`/stores/${storeId}/reviews${query}`),
      () => demoApi.getReviews(storeId, filters),
    );
  },
  getReview(storeId, reviewId) {
    return withFallback(
      () => request(`/stores/${storeId}/reviews/${reviewId}`),
      () => demoApi.getReview(storeId, reviewId),
    );
  },
  getStats(storeId, orderType) {
    const query = orderType && orderType !== 'all' ? `?order_type=${orderType}` : '';
    return withFallback(
      () => request(`/stores/${storeId}/reviews/stats${query}`),
      () => demoApi.getStats(storeId, orderType),
    );
  },
  analyzeReviews(storeId, reviewIds) {
    return withFallback(
      () =>
        request(`/stores/${storeId}/reviews/analyze`, {
          method: 'POST',
          body: { review_ids: reviewIds },
        }),
      () => demoApi.analyzeReviews(storeId, reviewIds),
    );
  },
  generateReplies(storeId, reviewIds) {
    return withFallback(
      () =>
        request(`/stores/${storeId}/reviews/generate-replies`, {
          method: 'POST',
          body: { review_ids: reviewIds },
        }),
      () => demoApi.generateReplies(storeId, reviewIds),
    );
  },
  approveReview(storeId, reviewId) {
    return withFallback(
      () => request(`/stores/${storeId}/reviews/${reviewId}/approve`, { method: 'POST' }),
      () => demoApi.approveReview(storeId, reviewId),
    );
  },
  rejectReview(storeId, reviewId) {
    return withFallback(
      () => request(`/stores/${storeId}/reviews/${reviewId}/reject`, { method: 'POST' }),
      () => demoApi.rejectReview(storeId, reviewId),
    );
  },
  regenerateReply(storeId, reviewId) {
    return withFallback(
      () => request(`/stores/${storeId}/reviews/${reviewId}/regenerate`, { method: 'POST' }),
      () => demoApi.regenerateReply(storeId, reviewId),
    );
  },
};
