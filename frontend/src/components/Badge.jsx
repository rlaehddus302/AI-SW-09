export default function Badge({ tone = 'neutral', children, size = 'md' }) {
  return <span className={`badge badge--${tone} badge--${size}`}>{children}</span>;
}
