import { useEffect, useRef } from "react";
import { useVoiceStore } from "../stores/voiceStore";
import { useAgentStore } from "../stores/agentStore";
import { useDashboardStore } from "../stores/dashboardStore";
import { useAppStore } from "../stores/appStore";
import { wsUrl } from "./runtime";
import type { WSMessage } from "./types";

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const setVoiceState = useVoiceStore((s) => s.setState);
  const setTranscript = useVoiceStore((s) => s.setTranscript);
  const updateAgent = useAgentStore((s) => s.updateAgent);
  const updateWidget = useDashboardStore((s) => s.updateWidget);

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(wsUrl);
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
            case "voice.transcript":
              setTranscript(msg.data.text);
              break;
            case "agent.status.update":
              updateAgent(msg.data.agent, msg.data.status);
              break;
            case "dashboard.update":
              updateWidget(msg.data.widget, msg.data.data);
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
  }, [setVoiceState, setTranscript, updateAgent, updateWidget]);
}
