import { Bike, CheckCircle2, ClipboardList, Store, Utensils } from 'lucide-react';
import { useState } from 'react';
import { api, API_BASE_URL, storeIdStorage } from '../services/api';

const defaultForm = {
  store_name: '',
  origin_info: '',
  is_dine_in: true,
  is_takeout: true,
  is_delivery: true,
};

export default function SetupPage({ onComplete }) {
  const [form, setForm] = useState(defaultForm);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const update = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const fillDemo = () => {
    setForm({
      store_name: '민트치킨 성수점',
      origin_info: '닭고기: 국내산, 감자: 미국산, 양배추: 국내산, 무: 국내산',
      is_dine_in: true,
      is_takeout: true,
      is_delivery: true,
    });
  };

  const submit = async (event) => {
    event.preventDefault();
    setError('');

    if (!form.store_name.trim()) {
      setError('가게 이름을 입력해 주세요.');
      return;
    }

    if (!form.is_dine_in && !form.is_takeout && !form.is_delivery) {
      setError('운영 유형을 하나 이상 선택해 주세요.');
      return;
    }

    setSubmitting(true);
    try {
      const store = await api.createStore({
        ...form,
        store_name: form.store_name.trim(),
        origin_info: form.origin_info.trim(),
      });
      storeIdStorage.set(store.id);
      onComplete();
    } catch (requestError) {
      setError(requestError.message || '가게 정보를 저장하지 못했습니다.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="setup-page">
      <section className="setup-shell">
        <div className="setup-visual" aria-hidden="true">
          <div className="setup-visual__badge">
            <CheckCircle2 size={22} />
            <span>로컬 데모</span>
          </div>
          <div className="ticket-stack">
            <div className="ticket ticket--front">
              <span>오늘의 리뷰</span>
              <strong>12건</strong>
              <small>승인 필요 3건</small>
            </div>
            <div className="ticket ticket--back">
              <span>자동 답변</span>
              <strong>5건</strong>
            </div>
          </div>
        </div>

        <form className="setup-form" onSubmit={submit}>
          <div className="setup-form__title">
            <span className="app-mark">
              <ClipboardList size={22} aria-hidden="true" />
            </span>
            <div>
              <h1>가게 정보 등록</h1>
              <p>대시보드에서 사용할 기본 매장 정보를 저장합니다.</p>
            </div>
          </div>

          <label className="field">
            <span>가게 이름</span>
            <input
              value={form.store_name}
              onChange={(event) => update('store_name', event.target.value)}
              placeholder="예: 민트치킨 성수점"
              autoComplete="organization"
            />
          </label>

          <label className="field">
            <span>원산지 정보</span>
            <textarea
              value={form.origin_info}
              onChange={(event) => update('origin_info', event.target.value)}
              placeholder="예: 닭고기: 국내산, 감자: 미국산"
              rows={5}
            />
          </label>

          <fieldset className="channel-field">
            <legend>운영 유형</legend>
            <label>
              <input
                type="checkbox"
                checked={form.is_dine_in}
                onChange={(event) => update('is_dine_in', event.target.checked)}
              />
              <Utensils size={18} aria-hidden="true" />
              홀
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.is_takeout}
                onChange={(event) => update('is_takeout', event.target.checked)}
              />
              <Store size={18} aria-hidden="true" />
              포장
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.is_delivery}
                onChange={(event) => update('is_delivery', event.target.checked)}
              />
              <Bike size={18} aria-hidden="true" />
              배달
            </label>
          </fieldset>

          {error ? <p className="form-error" role="alert">{error}</p> : null}

          <div className="setup-actions">
            <button type="button" className="button button--ghost" onClick={fillDemo}>
              데모 채우기
            </button>
            <button type="submit" className="button button--primary" disabled={submitting}>
              {submitting ? '저장 중' : '등록'}
            </button>
          </div>

          <p className="setup-form__foot">API: {API_BASE_URL}</p>
        </form>
      </section>
    </main>
  );
}
