export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
export const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000';

const STORE_ID_KEY = 'store_id';
export const DEMO_STORE_ID = '1';

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method || 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch {
    throw new ApiError(
      '백엔드 서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인해 주세요.',
      0,
    );
  }

  if (!response.ok) {
    let message = `API 요청 실패 (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data.detail === 'string') {
        message = data.detail;
      } else if (data.detail?.message) {
        message = data.detail.message;
      } else if (typeof data.message === 'string') {
        message = data.message;
      }
    } catch {
      // Keep the status-based message when the server returns no JSON body.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return null;
  return response.json();
}

export const storeIdStorage = {
  get() {
    return DEMO_STORE_ID;
  },
  set() {
    localStorage.setItem(STORE_ID_KEY, DEMO_STORE_ID);
  },
  clear() {
    localStorage.removeItem(STORE_ID_KEY);
  },
};

export const api = {
  createStore(payload) {
    return request('/stores', { method: 'POST', body: payload });
  },
  getStore(storeId) {
    return request(`/stores/${storeId}`);
  },
  updateStore(storeId, payload) {
    return request(`/stores/${storeId}`, { method: 'PUT', body: payload });
  },
  getReviews(storeId, filters = {}) {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value && value !== 'all') params.set(key, value);
    });
    const query = params.toString() ? `?${params.toString()}` : '';

    return request(`/stores/${storeId}/reviews${query}`);
  },
  getReview(storeId, reviewId) {
    return request(`/stores/${storeId}/reviews/${reviewId}`);
  },
  getStats(storeId, orderType) {
    const query = orderType && orderType !== 'all' ? `?order_type=${orderType}` : '';
    return request(`/stores/${storeId}/reviews/stats${query}`);
  },
  analyzeReviews(storeId, reviewIds) {
    return request(`/stores/${storeId}/reviews/analyze`, {
      method: 'POST',
      body: { review_ids: reviewIds },
    });
  },
  generateReplies(storeId, reviewIds) {
    return request(`/stores/${storeId}/reviews/generate-replies`, {
      method: 'POST',
      body: { review_ids: reviewIds },
    });
  },
  approveReview(storeId, reviewId) {
    return request(`/stores/${storeId}/reviews/${reviewId}/approve`, { method: 'POST' });
  },
  rejectReview(storeId, reviewId) {
    return request(`/stores/${storeId}/reviews/${reviewId}/reject`, { method: 'POST' });
  },
  regenerateReply(storeId, reviewId) {
    return request(`/stores/${storeId}/reviews/${reviewId}/regenerate`, { method: 'POST' });
  },
};
