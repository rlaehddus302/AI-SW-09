import {
  AlertCircle,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  MessageSquareText,
  RefreshCcw,
} from 'lucide-react';
import { orderTypeLabels, riskLabels, sentimentLabels, statusLabels } from '../constants';
import ApprovalActions from './ApprovalActions';
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

function EmptyState() {
  return (
    <aside className="detail-panel detail-panel--empty">
      <FileText size={34} aria-hidden="true" />
      <h2>리뷰를 선택하세요</h2>
      <p>목록에서 리뷰를 고르면 분석 결과와 답변 초안을 확인할 수 있습니다.</p>
    </aside>
  );
}

function Section({ icon: Icon, title, children }) {
  return (
    <section className="detail-section">
      <div className="detail-section__title">
        <Icon size={18} aria-hidden="true" />
        <h3>{title}</h3>
      </div>
      {children}
    </section>
  );
}

function Interpretation({ interpretation, tone }) {
  if (!interpretation) {
    return <p className="muted-text">아직 분석 결과가 없습니다.</p>;
  }

  return (
    <dl className="analysis-list">
      <div>
        <dt>핵심 이슈</dt>
        <dd>{interpretation.core_issue || '-'}</dd>
      </div>
      <div>
        <dt>답변 방향</dt>
        <dd>{interpretation.action_direction || '-'}</dd>
      </div>
      <div>
        <dt>답변 톤</dt>
        <dd>{interpretation.reply_tone || tone || '-'}</dd>
      </div>
    </dl>
  );
}

function StatusHint({ status }) {
  const messages = {
    pending: '분석 시작 후 감정, 위험도, 답변 방향이 채워집니다.',
    analyzing: '분류와 해석을 진행하고 있습니다.',
    analyzed: '분석이 끝났습니다. 답변 생성을 실행할 수 있습니다.',
    generating: '유사 사례를 찾고 답변 초안을 작성하고 있습니다.',
    auto_replied: '낮은 위험 리뷰로 자동 답변 완료 상태입니다.',
    needs_approval: '사장님 확인 후 승인 또는 반려가 필요한 리뷰입니다.',
    approved: '승인이 완료된 답변입니다.',
    on_hold: '보류된 답변입니다. 재생성 후 다시 검토할 수 있습니다.',
  };

  return (
    <div className={`status-hint status-hint--${status}`}>
      <AlertCircle size={18} aria-hidden="true" />
      <span>{messages[status] || '상태를 확인하세요.'}</span>
    </div>
  );
}

export default function ReviewDetailPanel({
  review,
  busy,
  onApprove,
  onReject,
  onRegenerate,
}) {
  if (!review) return <EmptyState />;

  const sentiment = review.sentiment ? sentimentLabels[review.sentiment] : '분석 대기';
  const risk = review.risk_level ? riskLabels[review.risk_level] : '분석 대기';

  return (
    <aside className="detail-panel">
      <div className="detail-panel__head">
        <div>
          <span>{orderTypeLabels[review.order_type]}</span>
          <h2>{review.reviewer_name || '익명 손님'} 리뷰</h2>
        </div>
        <Badge tone="info" size="lg">
          {statusLabels[review.status]}
        </Badge>
      </div>

      <StatusHint status={review.status} />

      <Section icon={MessageSquareText} title="리뷰 원문">
        <p className="review-quote">{review.review_text}</p>
      </Section>

      <Section icon={ClipboardCheck} title="분석 결과">
        <div className="detail-badges">
          <Badge tone={sentimentTone[review.sentiment] || 'neutral'} size="lg">
            {sentiment}
          </Badge>
          <Badge tone={riskTone[review.risk_level] || 'neutral'} size="lg">
            위험 {risk}
          </Badge>
          {review.sub_type ? <Badge tone="info" size="lg">{review.sub_type}</Badge> : null}
        </div>
        <Interpretation interpretation={review.interpretation} tone={review.reply_tone} />
      </Section>

      <Section icon={FileText} title="답변 초안">
        {review.reply_text ? (
          <p className="reply-box">{review.reply_text}</p>
        ) : (
          <p className="muted-text">답변 초안이 아직 생성되지 않았습니다.</p>
        )}
      </Section>

      {review.rag_references?.length ? (
        <Section icon={RefreshCcw} title="유사 사례">
          <div className="reference-list">
            {review.rag_references.map((reference, index) => (
              <article className="reference-item" key={`${reference.review}-${index}`}>
                <strong>참고 사례 {index + 1}</strong>
                <p>{reference.review}</p>
                <small>유사도 {Math.round((reference.similarity || 0) * 100)}%</small>
              </article>
            ))}
          </div>
        </Section>
      ) : null}

      {['auto_replied', 'approved'].includes(review.status) ? (
        <div className="complete-note">
          <CheckCircle2 size={18} aria-hidden="true" />
          <span>{review.status === 'approved' ? '승인 완료' : '자동 답변 완료'}</span>
        </div>
      ) : null}

      <ApprovalActions
        review={review}
        disabled={busy}
        onApprove={onApprove}
        onReject={onReject}
        onRegenerate={onRegenerate}
      />
    </aside>
  );
}
