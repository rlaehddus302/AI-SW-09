import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import App from './App';

function mockOfflineApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.reject(new TypeError('offline'))),
  );
}

describe('Review helper SPA', () => {
  beforeEach(() => {
    mockOfflineApi();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, '', '/');
  });

  test('setup validates required store name', async () => {
    window.history.pushState({}, '', '/setup');
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole('button', { name: '등록' }));

    expect(screen.getByRole('alert')).toHaveTextContent('가게 이름을 입력해 주세요.');
  });

  test('setup saves demo store and routes to dashboard', async () => {
    window.history.pushState({}, '', '/setup');
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole('button', { name: '데모 채우기' }));
    await user.click(screen.getByRole('button', { name: '등록' }));

    expect(await screen.findByRole('heading', { name: '민트치킨 성수점' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/dashboard');
    expect(localStorage.getItem('store_id')).toBe('1');
  });

  test('dashboard can select visible reviews and run batch analysis', async () => {
    localStorage.setItem('store_id', '1');
    window.history.pushState({}, '', '/dashboard');
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole('heading', { name: '민트치킨 성수점' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /전체 선택/ }));
    await user.click(screen.getByRole('button', { name: /분석 시작/ }));

    await waitFor(() => {
      expect(screen.getByText('분석이 완료되었습니다.')).toBeInTheDocument();
    });
  });
});
