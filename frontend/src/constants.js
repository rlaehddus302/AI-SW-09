export const orderTypeLabels = {
  all: '전체',
  dine_in: '홀',
  takeout: '포장',
  delivery: '배달',
};

export const sentimentLabels = {
  positive: '긍정',
  negative: '부정',
  malicious: '악성',
};

export const riskLabels = {
  low: '낮음',
  medium: '중간',
  high: '높음',
};

export const statusLabels = {
  pending: '미분석',
  analyzing: '분석중',
  analyzed: '분석완료',
  generating: '생성중',
  auto_replied: '자동답변',
  needs_approval: '승인필요',
  approved: '승인완료',
  on_hold: '보류',
};

export const statusOptions = [
  'all',
  'pending',
  'analyzed',
  'auto_replied',
  'needs_approval',
  'approved',
  'on_hold',
];

export const sentimentOptions = ['all', 'positive', 'negative', 'malicious'];

export function formatDate(value) {
  if (!value) return '-';
  return new Intl.DateTimeFormat('ko-KR', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

export function toPercent(value, total) {
  if (!total) return 0;
  return Math.round((value / total) * 100);
}
