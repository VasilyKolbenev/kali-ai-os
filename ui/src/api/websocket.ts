import { useEffect, useRef } from "react";
import { useVoiceStore } from "../stores/voiceStore";
import { useAgentStore } from "../stores/agentStore";
import { useDashboardStore } from "../stores/dashboardStore";
import { useCanvasStore } from "../stores/canvasStore";
import { useAppStore } from "../stores/appStore";
import { api } from "./client";
import { rustWsUrl } from "./runtime";
import type { WSMessage } from "./types";

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const setVoiceState = useVoiceStore((s) => s.setState);
  const setPipelineActive = useVoiceStore((s) => s.setPipelineActive);
  const setTranscript = useVoiceStore((s) => s.setTranscript);
  const updateAgent = useAgentStore((s) => s.updateAgent);
  const updateWidget = useDashboardStore((s) => s.updateWidget);
  const canvasAddOrUpdate = useCanvasStore((s) => s.addOrUpdate);
  const canvasClear = useCanvasStore((s) => s.clear);

  useEffect(() => {
    // Seed pipelineActive from /voice/status on mount — covers the case where
    // auto_start=true already started the pipeline before the WS connected.
    api
      .voiceStatus()
      .then((status) => {
        setPipelineActive(Boolean(status.started));
        if (status.state) setVoiceState(status.state);
      })
      .catch(() => {
        setPipelineActive(false);
      });

    const connect = () => {
      const ws = new WebSocket(rustWsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        useAppStore.getState().setKernelConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data);
          switch (msg.type) {
            case "voice.state":
              setVoiceState(msg.data.state);
              break;
            case "voice.pipeline":
              setPipelineActive(msg.data.active);
              break;
            case "voice.transcript":
              setTranscript(msg.data.text);
              break;
            case "agent.status.update":
              updateAgent(msg.data.agent, msg.data.status);
              break;
            case "dashboard.update":
              updateWidget(msg.data.widget, msg.data.data);
              break;
            case "canvas.update":
              if (msg.data.action === "clear_canvas") {
                canvasClear();
              } else if (msg.data.action === "render_widget" && msg.data.widget) {
                canvasAddOrUpdate(msg.data.widget);
              }
              break;
            case "system.models.download_progress":
              import("../stores/onboardingStore").then(({ useOnboardingStore }) => {
                useOnboardingStore.getState().setModelProgress(msg.data);
              });
              break;
            case "system.models.download_complete":
              import("../stores/onboardingStore").then(({ useOnboardingStore }) => {
                useOnboardingStore.getState().advance();
              });
              break;
          }
        } catch (e) {
          console.error("WS parse error:", e);
        }
      };

      ws.onclose = () => {
        useAppStore.getState().setKernelConnected(false);
        setTimeout(connect, 3000);
      };
    };

    connect();
    return () => wsRef.current?.close();
  }, [setVoiceState, setPipelineActive, setTranscript, updateAgent, updateWidget]);
}
