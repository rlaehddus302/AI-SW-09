import { AlertTriangle, CheckCircle2, ClipboardList, ShieldAlert, Sparkles } from 'lucide-react';
import { riskLabels, sentimentLabels, statusLabels, toPercent } from '../constants';

const sentimentTone = {
  positive: 'mint',
  negative: 'coral',
  malicious: 'ink',
};

const riskTone = {
  low: 'mint',
  medium: 'yellow',
  high: 'red',
};

function MetricCard({ icon: Icon, label, value, meta, tone }) {
  return (
    <article className={`metric metric--${tone}`}>
      <div className="metric__icon">
        <Icon size={22} aria-hidden="true" />
      </div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{meta}</small>
      </div>
    </article>
  );
}

function Distribution({ title, data, labels, tones }) {
  const total = Object.values(data || {}).reduce((sum, value) => sum + value, 0);

  return (
    <div className="distribution">
      <div className="distribution__head">
        <strong>{title}</strong>
        <span>{total}건</span>
      </div>
      <div className="distribution__bars">
        {Object.entries(labels).map(([key, label]) => {
          const value = data?.[key] || 0;
          const percent = toPercent(value, total);
          return (
            <div className="distribution__row" key={key}>
              <span>{label}</span>
              <div className="distribution__track" aria-hidden="true">
                <i
                  className={`distribution__bar distribution__bar--${tones[key]}`}
                  style={{ width: `${percent}%` }}
                />
              </div>
              <strong>{value}</strong>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function StatsCards({ stats }) {
  const status = stats?.status_distribution || {};
  const sentiment = stats?.sentiment_distribution || {};
  const risk = stats?.risk_distribution || {};
  const total = stats?.total_reviews || 0;
  const needsApproval = status.needs_approval || 0;
  const completed = (status.auto_replied || 0) + (status.approved || 0);
  const highRisk = risk.high || 0;

  return (
    <section className="stats-grid" aria-label="리뷰 통계">
      <MetricCard
        icon={ClipboardList}
        label="전체 리뷰"
        value={`${total}건`}
        meta="현재 필터 기준"
        tone="mint"
      />
      <MetricCard
        icon={Sparkles}
        label="긍정"
        value={`${sentiment.positive || 0}건`}
        meta="바로 감사 답변"
        tone="sky"
      />
      <MetricCard
        icon={ShieldAlert}
        label="승인 필요"
        value={`${needsApproval}건`}
        meta={statusLabels.needs_approval}
        tone="yellow"
      />
      <MetricCard
        icon={AlertTriangle}
        label="높은 위험"
        value={`${highRisk}건`}
        meta="직접 확인 권장"
        tone="coral"
      />
      <MetricCard
        icon={CheckCircle2}
        label="처리 완료"
        value={`${completed}건`}
        meta="자동답변 + 승인"
        tone="leaf"
      />
      <Distribution
        title="감정 분포"
        data={sentiment}
        labels={sentimentLabels}
        tones={sentimentTone}
      />
      <Distribution title="위험도 분포" data={risk} labels={riskLabels} tones={riskTone} />
    </section>
  );
}
