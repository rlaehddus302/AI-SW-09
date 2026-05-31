import { Check, PauseCircle, RotateCcw, WandSparkles } from 'lucide-react';

export default function ApprovalActions({ review, disabled, onApprove, onReject, onRegenerate }) {
  if (!review) return null;

  if (review.status === 'needs_approval') {
    return (
      <div className="approval-actions">
        <button type="button" className="button button--primary" disabled={disabled} onClick={onApprove}>
          <Check size={18} aria-hidden="true" />
          승인
        </button>
        <button type="button" className="button button--ghost" disabled={disabled} onClick={onReject}>
          <PauseCircle size={18} aria-hidden="true" />
          반려
        </button>
      </div>
    );
  }

  if (review.status === 'on_hold') {
    return (
      <div className="approval-actions">
        <button
          type="button"
          className="button button--primary"
          disabled={disabled}
          onClick={onRegenerate}
        >
          <RotateCcw size={18} aria-hidden="true" />
          재생성
        </button>
      </div>
    );
  }

  if (review.status === 'analyzed') {
    return (
      <div className="approval-actions">
        <button
          type="button"
          className="button button--primary"
          disabled={disabled}
          onClick={onRegenerate}
        >
          <WandSparkles size={18} aria-hidden="true" />
          답변 생성
        </button>
      </div>
    );
  }

  return null;
}
