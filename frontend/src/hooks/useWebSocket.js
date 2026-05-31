import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { WS_BASE_URL } from '../services/api';

const DISABLED = import.meta.env.VITE_DISABLE_WS === 'true';
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 5_000;
const MAX_BUFFERED_MESSAGES = 100;

export function useWebSocket(storeId) {
  const socketRef = useRef(null);
  const retryTimerRef = useRef(null);
  const manualCloseRef = useRef(false);
  const retryCountRef = useRef(0);
  const messageSeqRef = useRef(0);
  const [status, setStatus] = useState(DISABLED ? 'disabled' : 'idle');
  const [retryCount, setRetryCount] = useState(0);
  const [lastMessage, setLastMessage] = useState(null);
  const [messages, setMessages] = useState([]);
  const [error, setError] = useState('');

  const wsUrl = useMemo(() => {
    if (!storeId) return '';
    const base = WS_BASE_URL.replace(/\/$/, '');
    return `${base}/ws/${storeId}`;
  }, [storeId]);

  const cleanup = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }

    if (socketRef.current) {
      socketRef.current.onopen = null;
      socketRef.current.onmessage = null;
      socketRef.current.onerror = null;
      socketRef.current.onclose = null;
      socketRef.current.close();
      socketRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (DISABLED || !wsUrl) return;

    cleanup();
    manualCloseRef.current = false;
    setStatus('connecting');
    setError('');

    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;

    socket.onopen = () => {
      retryCountRef.current = 0;
      setRetryCount(0);
      setStatus('open');
      setError('');
    };

    socket.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        message = { type: 'message', raw: event.data };
      }

      messageSeqRef.current += 1;
      const bufferedMessage = { id: messageSeqRef.current, payload: message };
      setLastMessage(message);
      setMessages((prev) => [...prev, bufferedMessage].slice(-MAX_BUFFERED_MESSAGES));
    };

    socket.onerror = () => {
      setError('실시간 연결을 확인할 수 없습니다.');
    };

    socket.onclose = () => {
      socketRef.current = null;
      if (manualCloseRef.current) {
        setStatus('closed');
        return;
      }

      const nextRetry = retryCountRef.current + 1;
      if (nextRetry > MAX_RETRIES) {
        setStatus('failed');
        setError('자동 재연결 한도를 초과했습니다.');
        return;
      }

      retryCountRef.current = nextRetry;
      setRetryCount(nextRetry);
      setStatus('reconnecting');
      retryTimerRef.current = setTimeout(connect, RETRY_DELAY_MS);
    };
  }, [cleanup, wsUrl]);

  const disconnect = useCallback(() => {
    manualCloseRef.current = true;
    cleanup();
    setStatus('closed');
  }, [cleanup]);

  const reconnect = useCallback(() => {
    retryCountRef.current = 0;
    setRetryCount(0);
    connect();
  }, [connect]);

  useEffect(() => {
    if (DISABLED || !wsUrl) return undefined;
    connect();

    return () => {
      manualCloseRef.current = true;
      cleanup();
    };
  }, [cleanup, connect, wsUrl]);

  return {
    status,
    retryCount,
    lastMessage,
    messages,
    error,
    reconnect,
    disconnect,
    wsUrl,
    maxRetries: MAX_RETRIES,
  };
}
