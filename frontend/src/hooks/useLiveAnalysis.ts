// Live engine analysis over the backend WebSocket (/api/v1/analysis/live).
//
// * One socket per hook instance, reconnected with backoff if it drops.
// * Each start() gets a request id; messages for older requests are ignored,
//   so a fast click-through of positions never shows stale lines.
// * Starting a new analysis implicitly stops the previous one (server side).

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import type { AnalysisSnapshot, EngineId } from "@/types/api";

export interface LiveParams {
  fen?: string | null;
  moves?: string[];
  engine?: EngineId;
  multipv?: number;
  depth?: number | null;
  movetime_ms?: number | null;
}

type Status = "connecting" | "idle" | "running" | "error" | "offline";

interface ServerMessage {
  type: "update" | "done" | "error";
  request_id: string | null;
  snapshot?: AnalysisSnapshot;
  code?: string;
  message?: string;
}

function socketUrl(): string {
  const { protocol, host } = window.location;
  return `${protocol === "https:" ? "wss" : "ws"}://${host}${API_BASE}/analysis/live`;
}

export function useLiveAnalysis() {
  const socketRef = useRef<WebSocket | null>(null);
  const currentRequest = useRef<string | null>(null);
  const counter = useRef(0);
  const pending = useRef<Record<string, unknown> | null>(null);
  const retry = useRef(0);
  const [status, setStatus] = useState<Status>("connecting");
  const [snapshot, setSnapshot] = useState<AnalysisSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;

    const connect = () => {
      if (disposed) return;
      const ws = new WebSocket(socketUrl());
      socketRef.current = ws;
      ws.onopen = () => {
        retry.current = 0;
        setStatus("idle");
        if (pending.current) {
          ws.send(JSON.stringify(pending.current));
          pending.current = null;
          setStatus("running");
        }
      };
      ws.onmessage = (event) => {
        let message: ServerMessage;
        try {
          message = JSON.parse(event.data as string) as ServerMessage;
        } catch {
          return;
        }
        if (message.request_id !== currentRequest.current) return; // stale
        if (message.type === "error") {
          setError(message.message ?? "Analysis failed.");
          setStatus("error");
          return;
        }
        if (message.snapshot) setSnapshot(message.snapshot);
        if (message.type === "done") setStatus("idle");
      };
      ws.onclose = () => {
        // A replaced socket (e.g. React StrictMode remount) must not clear its successor.
        if (socketRef.current === ws) socketRef.current = null;
        if (disposed) return;
        setStatus("offline");
        const delay = Math.min(10_000, 500 * 2 ** retry.current);
        retry.current += 1;
        timer = window.setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      socketRef.current?.close();
    };
  }, []);

  const start = useCallback((params: LiveParams) => {
    counter.current += 1;
    const requestId = `r${counter.current}`;
    currentRequest.current = requestId;
    setError(null);
    setSnapshot(null);
    const message = { type: "start", request_id: requestId, ...params };
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message));
      setStatus("running");
    } else {
      pending.current = message; // sent as soon as the socket opens
      setStatus("connecting");
    }
  }, []);

  const stop = useCallback(() => {
    pending.current = null;
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "stop" }));
  }, []);

  const clear = useCallback(() => {
    currentRequest.current = null;
    setSnapshot(null);
    setError(null);
  }, []);

  return { status, snapshot, error, start, stop, clear, running: status === "running" };
}
