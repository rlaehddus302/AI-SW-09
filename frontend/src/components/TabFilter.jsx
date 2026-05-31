import { Bike, Grid2X2, Store, Utensils } from 'lucide-react';
import { orderTypeLabels } from '../constants';

const icons = {
  all: Grid2X2,
  dine_in: Utensils,
  takeout: Store,
  delivery: Bike,
};

export default function TabFilter({ value, onChange, counts = {} }) {
  return (
    <div className="tab-filter" aria-label="주문 유형 필터">
      {Object.keys(orderTypeLabels).map((key) => {
        const Icon = icons[key];
        const selected = value === key;
        return (
          <button
            key={key}
            type="button"
            className={`tab-filter__button ${selected ? 'is-active' : ''}`}
            onClick={() => onChange(key)}
            aria-pressed={selected}
          >
            <Icon size={18} aria-hidden="true" />
            <span>{orderTypeLabels[key]}</span>
            <strong>{counts[key] ?? 0}</strong>
          </button>
        );
      })}
    </div>
  );
}
