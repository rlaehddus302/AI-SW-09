import {
  Activity,
  CheckSquare,
  CircleAlert,
  ClipboardList,
  Loader2,
  RefreshCcw,
  Settings,
  Square,
  WandSparkles,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReviewCard from '../components/ReviewCard';
import ReviewDetailPanel from '../components/ReviewDetailPanel';
import StatsCards from '../components/StatsCards';
import TabFilter from '../components/TabFilter';
import {
  sentimentLabels,
  sentimentOptions,
  statusLabels,
  statusOptions,
} from '../constants';
import { useWebSocket } from '../hooks/useWebSocket';
import { api, storeIdStorage } from '../services/api';

const listSize = 50;
const maxReviewPageSize = 100;
const activityLimit = 6;
const sentimentKeys = ['positive', 'negative', 'malicious'];
const riskKeys = ['low', 'medium', 'high'];
const finalReviewEvents = new Set([
  'analysis_completed',
  'analysis_failed',
  'generation_completed',
  'generation_failed',
]);
const taskTypeLabels = {
  analysis_progress: '분석',
  generation_progress: '답변 생성',
};
const stepLabels = {
  classification: '분류',
  interpretation: '해석',
  rag_search: '유사 사례 검색',
  reply_generation: '답변 작성',
  self_review: '자기 점검',
  approval_gate: '승인 기준 확인',
  analysis: '분석',
  generation: '답변 생성',
};

function makeCounts(reviews) {
  return reviews.reduce(
    (acc, review) => {
      acc.all += 1;
      acc[review.order_type] = (acc[review.order_type] || 0) + 1;
      return acc;
    },
    { all: 0, dine_in: 0, takeout: 0, delivery: 0 },
  );
}

function makeStats(reviews, orderType = 'all') {
  const scopedReviews = reviews.filter((review) => (
    orderType === 'all' || review.order_type === orderType
  ));
  const sentimentDistribution = Object.fromEntries(sentimentKeys.map((key) => [key, 0]));
  const riskDistribution = Object.fromEntries(riskKeys.map((key) => [key, 0]));
  const statusDistribution = Object.fromEntries(Object.keys(statusLabels).map((key) => [key, 0]));
  const subTypeDistribution = {};

  scopedReviews.forEach((review) => {
    if (review.sentiment) sentimentDistribution[review.sentiment] += 1;
    if (review.risk_level) riskDistribution[review.risk_level] += 1;
    if (review.status) statusDistribution[review.status] += 1;
    if (review.sub_type) subTypeDistribution[review.sub_type] = (subTypeDistribution[review.sub_type] || 0) + 1;
  });

  return {
    total_reviews: scopedReviews.length,
    sentiment_distribution: sentimentDistribution,
    risk_distribution: riskDistribution,
    status_distribution: statusDistribution,
    sub_type_distribution: subTypeDistribution,
  };
}

function matchesFilters(review, { orderType, statusFilter, sentimentFilter }) {
  if (orderType !== 'all' && review.order_type !== orderType) return false;
  if (statusFilter !== 'all' && review.status !== statusFilter) return false;
  if (sentimentFilter !== 'all' && review.sentiment !== sentimentFilter) return false;
  return true;
}

function mergeReview(reviews, updatedReview, { include }) {
  const exists = reviews.some((review) => review.id === updatedReview.id);
  if (!include) return reviews.filter((review) => review.id !== updatedReview.id);
  if (!exists) return [updatedReview, ...reviews];
  return reviews.map((review) => (review.id === updatedReview.id ? { ...review, ...updatedReview } : review));
}

function formatProgressActivity(message) {
  const taskLabel = taskTypeLabels[message.type] || '작업';
  const stepLabel = stepLabels[message.step] || message.step || '처리';
  const current = message.progress?.current ?? 0;
  const total = message.progress?.total ?? 0;
  const percentage = message.progress?.percentage ?? 0;

  if (message.step === 'self_review' && message.status !== 'started') {
    const resultLabel = message.status === 'passed'
      ? '통과'
      : `실패${message.reason ? ` — ${message.reason}` : ''}`;
    return `${taskLabel}: ${stepLabel} ${resultLabel} (${message.attempt}회차)`;
  }

  return `${taskLabel}: ${stepLabel} ${current}/${total} (${percentage}%)`;
}

function connectionLabel(status) {
  const labels = {
    disabled: '테스트 모드',
    idle: '대기',
    connecting: '연결 중',
    open: '실시간 연결',
    reconnecting: '재연결 중',
    failed: '재연결 실패',
    closed: '연결 종료',
  };
  return labels[status] || status;
}

export default function DashboardPage({ onSetup }) {
  const [store, setStore] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [allReviews, setAllReviews] = useState([]);
  const [stats, setStats] = useState(null);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [selectedReviewId, setSelectedReviewId] = useState(null);
  const [selectedReview, setSelectedReview] = useState(null);
  const [orderType, setOrderType] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sentimentFilter, setSentimentFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState('');
  const [activity, setActivity] = useState([]);
  const processedMessageIdRef = useRef(0);
  const storeId = storeIdStorage.get();
  const ws = useWebSocket(store?.id || storeId);

  const tabCounts = useMemo(() => makeCounts(allReviews), [allReviews]);
  const visibleIds = useMemo(() => reviews.map((review) => review.id), [reviews]);
  const selectedVisibleCount = visibleIds.filter((id) => selectedIds.has(id)).length;
  const allVisibleSelected = visibleIds.length > 0 && selectedVisibleCount === visibleIds.length;

  const pushActivity = useCallback((message, type = 'info', key = null) => {
    setActivity((prev) => {
      const id = key || `${Date.now()}_${Math.random()}`;
      const nextItem = { id, message, type, time: new Date() };
      const previousItems = key ? prev.filter((item) => item.id !== key) : prev;
      return [nextItem, ...previousItems].slice(0, activityLimit);
    });
  }, []);

  const applyRealtimeReview = useCallback(
    (updatedReview) => {
      const include = matchesFilters(updatedReview, { orderType, statusFilter, sentimentFilter });

      setReviews((prev) => mergeReview(prev, updatedReview, { include }));
      setAllReviews((prev) => {
        const next = mergeReview(prev, updatedReview, { include: true });
        setStats(makeStats(next, orderType));
        return next;
      });
      setSelectedReview((prev) => (
        prev?.id === updatedReview.id ? { ...prev, ...updatedReview } : prev
      ));
    },
    [orderType, sentimentFilter, statusFilter],
  );

  const applyLocalReviewPatch = useCallback(
    (reviewIds, patch) => {
      const idSet = new Set(reviewIds);
      const patchReview = (review) => (idSet.has(review.id) ? { ...review, ...patch } : review);

      setReviews((prev) => prev
        .map(patchReview)
        .filter((review) => matchesFilters(review, { orderType, statusFilter, sentimentFilter })));
      setAllReviews((prev) => {
        const next = prev.map(patchReview);
        setStats(makeStats(next, orderType));
        return next;
      });
      setSelectedReview((prev) => (prev && idSet.has(prev.id) ? { ...prev, ...patch } : prev));
    },
    [orderType, sentimentFilter, statusFilter],
  );

  const loadDashboard = useCallback(
    async ({ preserveSelection = true, silent = false } = {}) => {
      if (!storeId) return;
      setError('');
      if (!silent) setLoading(true);

      try {
        const filters = {
          order_type: orderType,
          status: statusFilter,
          sentiment: sentimentFilter,
          page: 1,
          size: listSize,
        };

        const [storeData, reviewData, statsData, allData] = await Promise.all([
          api.getStore(storeId),
          api.getReviews(storeId, filters),
          api.getStats(storeId, orderType),
          api.getReviews(storeId, { page: 1, size: maxReviewPageSize }),
        ]);

        const nextReviews = reviewData.reviews || [];
        const nextAllReviews = allData.reviews || [];
        setStore(storeData);
        setReviews(nextReviews);
        setStats(statsData);
        setAllReviews(nextAllReviews);
        setSelectedReview((prev) => {
          if (!prev) return prev;
          const refreshedReview = nextAllReviews.find((review) => review.id === prev.id);
          return refreshedReview ? { ...prev, ...refreshedReview } : prev;
        });

        setSelectedIds((prev) => {
          if (!preserveSelection) return new Set();
          const next = new Set([...prev].filter((id) => nextReviews.some((review) => review.id === id)));
          return next;
        });

        setSelectedReviewId((prev) => {
          if (prev && nextReviews.some((review) => review.id === prev)) return prev;
          return nextReviews[0]?.id || null;
        });
      } catch (requestError) {
        setError(requestError.message || '대시보드를 불러오지 못했습니다.');
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [orderType, sentimentFilter, statusFilter, storeId],
  );

  const loadDetail = useCallback(
    async (reviewId) => {
      if (!storeId || !reviewId) {
        setSelectedReview(null);
        return;
      }

      setDetailLoading(true);
      try {
        const detail = await api.getReview(storeId, reviewId);
        setSelectedReview(detail);
      } catch (requestError) {
        pushActivity(requestError.message || '리뷰 상세를 불러오지 못했습니다.', 'error');
      } finally {
        setDetailLoading(false);
      }
    },
    [pushActivity, storeId],
  );

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  useEffect(() => {
    loadDetail(selectedReviewId);
  }, [loadDetail, selectedReviewId]);

  useEffect(() => {
    setSelectedIds((prev) => new Set([...prev].filter((id) => visibleIds.includes(id))));
  }, [visibleIds]);

  const handleRealtimeMessage = useCallback((message) => {
    if (message.type === 'review_updated' && message.review) {
      applyRealtimeReview(message.review);
      if (finalReviewEvents.has(message.event)) {
        const name = message.review.reviewer_name || `#${message.review.id}`;
        const type = message.status === 'failed' ? 'error' : 'success';
        pushActivity(
          `${name} 리뷰: ${statusLabels[message.review.status] || message.review.status}`,
          type,
          `review:${message.task_id}:${message.review.id}:${message.event}`,
        );
      }
      return;
    }

    if (message.type === 'task_complete') {
      const success = message.summary?.success ?? 0;
      const total = message.summary?.total ?? success;
      const failed = message.summary?.failed ?? 0;
      const text = failed
        ? `작업 완료: ${success}/${total}건 처리, ${failed}건 실패`
        : `작업 완료: ${success}/${total}건 처리`;
      pushActivity(text, failed ? 'error' : 'success', `task:${message.task_id}`);
      void loadDashboard({ preserveSelection: true, silent: true });
      return;
    }

    if (message.type === 'error') {
      pushActivity(
        message.error || '실시간 작업 오류가 발생했습니다.',
        'error',
        `error:${message.task_id}:${message.review_id || 'task'}`,
      );
      return;
    }

    if (message.progress) {
      pushActivity(formatProgressActivity(message), 'info', `task:${message.task_id || message.type}`);
    }
  }, [applyRealtimeReview, loadDashboard, pushActivity]);

  useEffect(() => {
    const nextMessages = ws.messages.filter((message) => message.id > processedMessageIdRef.current);
    if (!nextMessages.length) return;

    nextMessages.forEach((message) => handleRealtimeMessage(message.payload));
    processedMessageIdRef.current = nextMessages[nextMessages.length - 1].id;
  }, [handleRealtimeMessage, ws.messages]);

  const toggleReview = (reviewId, checked) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(reviewId);
      else next.delete(reviewId);
      return next;
    });
  };

  const toggleVisible = () => {
    setSelectedIds((prev) => {
      if (allVisibleSelected) return new Set([...prev].filter((id) => !visibleIds.includes(id)));
      return new Set([...prev, ...visibleIds]);
    });
  };

  const runAction = async (message, action, options = {}) => {
    setActionBusy(true);
    setError('');
    try {
      const result = await action();
      if (options.patchReviewIds?.length && options.patch) {
        applyLocalReviewPatch(options.patchReviewIds, options.patch);
      }
      pushActivity(
        result?.message || message,
        options.type || 'success',
        options.trackTask && result?.task_id ? `task:${result.task_id}` : null,
      );
      if (options.reloadOnSuccess !== false) {
        await loadDashboard({ preserveSelection: options.preserveSelection ?? true });
        if (selectedReviewId) await loadDetail(selectedReviewId);
      }
    } catch (requestError) {
      const actionError = requestError.message || '요청을 처리하지 못했습니다.';
      setError(actionError);
      pushActivity(actionError, 'error');
    } finally {
      setActionBusy(false);
    }
  };

  const selectedBatchIds = [...selectedIds];

  const analyzeSelected = () => {
    if (!selectedBatchIds.length || !storeId) return;
    const reviewIds = [...selectedBatchIds];
    runAction(
      `${reviewIds.length}건 분석을 시작했습니다.`,
      () => api.analyzeReviews(storeId, reviewIds),
      {
        patchReviewIds: reviewIds,
        patch: { status: 'analyzing' },
        preserveSelection: true,
        reloadOnSuccess: false,
        trackTask: true,
        type: 'info',
      },
    );
  };

  const generateSelected = () => {
    if (!selectedBatchIds.length || !storeId) return;
    const reviewIds = [...selectedBatchIds];
    runAction(
      `${reviewIds.length}건 답변 생성을 시작했습니다.`,
      () => api.generateReplies(storeId, reviewIds),
      {
        patchReviewIds: reviewIds,
        patch: { status: 'generating' },
        preserveSelection: true,
        reloadOnSuccess: false,
        trackTask: true,
        type: 'info',
      },
    );
  };

  const approveSelected = () => {
    if (!selectedReview || !storeId) return;
    runAction('답변을 승인했습니다.', () => api.approveReview(storeId, selectedReview.id));
  };

  const rejectSelected = () => {
    if (!selectedReview || !storeId) return;
    runAction('답변을 보류했습니다.', () => api.rejectReview(storeId, selectedReview.id));
  };

  const regenerateSelected = () => {
    if (!selectedReview || !storeId) return;
    const reviewId = selectedReview.id;
    const action =
      selectedReview.status === 'analyzed'
        ? () => api.generateReplies(storeId, [reviewId])
        : () => api.regenerateReply(storeId, reviewId);
    runAction('답변을 다시 생성했습니다.', action, {
      patchReviewIds: [reviewId],
      patch: { status: 'generating' },
      reloadOnSuccess: false,
      trackTask: true,
      type: 'info',
    });
  };

  const resetStore = () => {
    storeIdStorage.clear();
    onSetup();
  };

  return (
    <main className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <span className="eyebrow">리뷰 대응 에이전트</span>
          <h1>{store?.store_name || '가게 리뷰 관리'}</h1>
        </div>
        <div className="header-actions">
          <div className={`ws-pill ws-pill--${ws.status}`}>
            {ws.status === 'open' ? <Wifi size={16} /> : <WifiOff size={16} />}
            <span>{connectionLabel(ws.status)}</span>
            {ws.status === 'reconnecting' ? <small>{ws.retryCount}/{ws.maxRetries}</small> : null}
          </div>
          {['failed', 'closed'].includes(ws.status) ? (
            <button type="button" className="icon-button" onClick={ws.reconnect} aria-label="실시간 재연결">
              <RefreshCcw size={18} aria-hidden="true" />
            </button>
          ) : null}
          <button type="button" className="button button--ghost" onClick={resetStore}>
            <Settings size={18} aria-hidden="true" />
            가게 설정
          </button>
        </div>
      </header>

      {error ? (
        <div className="page-alert" role="alert">
          <CircleAlert size={18} aria-hidden="true" />
          <span>{error}</span>
        </div>
      ) : null}

      <StatsCards stats={stats} />

      <section className="dashboard-controls">
        <TabFilter value={orderType} onChange={setOrderType} counts={tabCounts} />

        <div className="filters-row">
          <label>
            상태
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              {statusOptions.map((option) => (
                <option key={option} value={option}>
                  {option === 'all' ? '전체' : statusLabels[option]}
                </option>
              ))}
            </select>
          </label>
          <label>
            감정
            <select
              value={sentimentFilter}
              onChange={(event) => setSentimentFilter(event.target.value)}
            >
              {sentimentOptions.map((option) => (
                <option key={option} value={option}>
                  {option === 'all' ? '전체' : sentimentLabels[option]}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="button button--soft" onClick={() => loadDashboard()}>
            <RefreshCcw size={18} aria-hidden="true" />
            새로고침
          </button>
        </div>

        <div className="batch-actions">
          <button type="button" className="button button--ghost" onClick={toggleVisible}>
            {allVisibleSelected ? <CheckSquare size={18} /> : <Square size={18} />}
            {allVisibleSelected ? '선택 해제' : '전체 선택'}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!selectedBatchIds.length || actionBusy}
            onClick={analyzeSelected}
          >
            <Activity size={18} aria-hidden="true" />
            분석 시작
          </button>
          <button
            type="button"
            className="button button--accent"
            disabled={!selectedBatchIds.length || actionBusy}
            onClick={generateSelected}
          >
            <WandSparkles size={18} aria-hidden="true" />
            답변 생성
          </button>
          <span className="selected-count">{selectedBatchIds.length}건 선택</span>
        </div>
      </section>

      <section className="workspace">
        <div className="review-list">
          <div className="panel-title">
            <ClipboardList size={18} aria-hidden="true" />
            <h2>리뷰 목록</h2>
            {loading ? <Loader2 className="spin" size={18} aria-hidden="true" /> : null}
          </div>

          {reviews.length ? (
            <div className="review-list__items">
              {reviews.map((review) => (
                <ReviewCard
                  key={review.id}
                  review={review}
                  selected={selectedReviewId === review.id}
                  checked={selectedIds.has(review.id)}
                  onOpen={setSelectedReviewId}
                  onToggle={toggleReview}
                />
              ))}
            </div>
          ) : (
            <div className="empty-list">
              <ClipboardList size={28} aria-hidden="true" />
              <strong>표시할 리뷰가 없습니다</strong>
              <span>필터를 변경하거나 새로고침해 주세요.</span>
            </div>
          )}
        </div>

        <div className="detail-wrap">
          {detailLoading ? (
            <div className="detail-loading">
              <Loader2 className="spin" size={24} aria-hidden="true" />
              <span>상세 불러오는 중</span>
            </div>
          ) : (
            <ReviewDetailPanel
              review={selectedReview}
              busy={actionBusy}
              onApprove={approveSelected}
              onReject={rejectSelected}
              onRegenerate={regenerateSelected}
            />
          )}

          <section className="activity-panel">
            <div className="panel-title">
              <Activity size={18} aria-hidden="true" />
              <h2>작업 상태</h2>
            </div>
            {activity.length ? (
              <ul>
                {activity.map((item) => (
                  <li key={item.id} className={`activity-panel__item activity-panel__item--${item.type}`}>
                    <span>{item.message}</span>
                    <time>{item.time.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}</time>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted-text">아직 실행된 작업이 없습니다.</p>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}
