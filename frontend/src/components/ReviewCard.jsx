import { ChevronRight, Star } from 'lucide-react';
import { formatDate, orderTypeLabels, riskLabels, sentimentLabels, statusLabels } from '../constants';
import Badge from './Badge';

const sentimentTone = {
  positive: 'positive',
  negative: 'negative',
  malicious: 'malicious',
};

const riskTone = {
  low: 'low',
  medium: 'medium',
  high: 'high',
};

const statusTone = {
  pending: 'neutral',
  analyzing: 'working',
  analyzed: 'info',
  generating: 'working',
  auto_replied: 'done',
  needs_approval: 'warning',
  approved: 'done',
  on_hold: 'hold',
};

function Rating({ value = 0 }) {
  return (
    <span className="rating" aria-label={`별점 ${value}점`}>
      {Array.from({ length: 5 }).map((_, index) => (
        <Star
          key={index}
          size={14}
          aria-hidden="true"
          className={index < value ? 'rating__star is-filled' : 'rating__star'}
        />
      ))}
    </span>
  );
}

export default function ReviewCard({
  review,
  selected,
  checked,
  onOpen,
  onToggle,
}) {
  const sentiment = review.sentiment ? sentimentLabels[review.sentiment] : '대기';
  const risk = review.risk_level ? riskLabels[review.risk_level] : '대기';

  return (
    <article className={`review-card ${selected ? 'is-selected' : ''}`}>
      <label className="check-pill">
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => onToggle(review.id, event.target.checked)}
          aria-label={`${review.reviewer_name} 리뷰 선택`}
        />
        <span aria-hidden="true" />
      </label>
      <button type="button" className="review-card__body" onClick={() => onOpen(review.id)}>
        <div className="review-card__topline">
          <strong>{review.reviewer_name || '익명 손님'}</strong>
          <span>{formatDate(review.created_at)}</span>
        </div>
        <div className="review-card__meta">
          <Rating value={review.rating || 0} />
          <span>{orderTypeLabels[review.order_type]}</span>
        </div>
        <p>{review.review_text}</p>
        <div className="review-card__badges">
          <Badge tone={sentimentTone[review.sentiment] || 'neutral'}>{sentiment}</Badge>
          <Badge tone={riskTone[review.risk_level] || 'neutral'}>위험 {risk}</Badge>
          <Badge tone={statusTone[review.status] || 'neutral'}>{statusLabels[review.status]}</Badge>
        </div>
      </button>
      <ChevronRight className="review-card__chevron" size={18} aria-hidden="true" />
    </article>
  );
}
