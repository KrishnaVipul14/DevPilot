"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage, isNotFound } from "./api";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  notFound: boolean;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (d: T | null) => void;
}

/**
 * Fetch data client-side and refetch whenever `key` changes (pass the
 * DataProvider `version` so data refreshes after each new scan).
 */
export function useApi<T>(fetcher: () => Promise<T>, key: unknown): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fetcherRef.current();
      setData(d);
      setError(null);
      setNotFound(false);
    } catch (err) {
      setNotFound(isNotFound(err));
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, key]);

  return { data, error, notFound, loading, reload, setData };
}
