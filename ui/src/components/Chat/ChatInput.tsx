import { useState, useRef, useEffect } from "react";
import { useChatStore } from "../../stores/chatStore";
import { useVoiceStore } from "../../stores/voiceStore";
import { api } from "../../api/client";

/* eslint-disable @typescript-eslint/no-explicit-any */
type SpeechRecognitionInstance = any;

// JARVIS-style sound effects from original repo
const SOUNDS = {
  reply: ["/sounds/reply1.mp3", "/sounds/reply2.mp3", "/sounds/reply3.mp3", "/sounds/reply4.mp3", "/sounds/reply5.mp3", "/sounds/reply6.mp3"],
  ok: ["/sounds/ok1.mp3", "/sounds/ok2.mp3", "/sounds/ok3.mp3", "/sounds/ok4.mp3"],
  greet: ["/sounds/greet1.mp3", "/sounds/greet_morning.mp3"],
};

function playSound(category: keyof typeof SOUNDS) {
  const files = SOUNDS[category];
  const file = files[Math.floor(Math.random() * files.length)];
  const audio = new Audio(file);
  audio.volume = 0.7;
  audio.play().catch(() => {});
}

export function ChatInput() {
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const messages = useChatStore((s) => s.messages);
  const addMessage = useChatStore((s) => s.addMessage);
  const isLoading = useChatStore((s) => s.isLoading);
  const setLoading = useChatStore((s) => s.setLoading);
  const setVoiceState = useVoiceStore((s) => s.setState);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<SpeechRecognitionInstance>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // No system TTS — only JARVIS voice sounds

  // Global hotkey: hold Space = push-to-talk (when input not focused)
  useEffect(() => {
    const inputFocused = () => document.activeElement?.tagName === "INPUT";

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Space" && !inputFocused() && !listening && !isLoading) {
        e.preventDefault();
        toggleMic();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [listening, isLoading]);

  const send = async (msg: string) => {
    if (!msg.trim() || isLoading) return;
    addMessage("user", msg.trim());
    setText("");
    setLoading(true);
    setVoiceState("thinking");

    try {
      const res = await api.chat(msg.trim());
      addMessage("assistant", res.response, res.source);
      playSound("ok"); // JARVIS "done" sound — no extra words
    } catch {
      addMessage("assistant", "Connection error. Is the kernel running?", "error");
    } finally {
      setLoading(false);
      setVoiceState("idle");
    }
  };

  const toggleMic = () => {
    const SpeechRecognitionCtor =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) {
      addMessage(
        "assistant",
        "Speech recognition not supported in this browser. Use Chrome.",
        "error",
      );
      return;
    }

    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      setVoiceState("idle");
      return;
    }

    const recognition = new SpeechRecognitionCtor();
    recognition.lang = "ru-RU";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognitionRef.current = recognition;

    recognition.onstart = () => {
      setListening(true);
      setVoiceState("listening");
      playSound("reply"); // JARVIS "I'm listening" sound
    };

    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      send(transcript);
      setListening(false);
      setVoiceState("idle");
    };

    recognition.onerror = () => {
      setListening(false);
      setVoiceState("idle");
    };

    recognition.onend = () => {
      setListening(false);
      setVoiceState("idle");
    };

    // Load voices (needed for Chrome)
    window.speechSynthesis?.getVoices();

    recognition.start();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(text);
    }
  };

  const recentMessages = messages.slice(-6);

  return (
    <div className="w-full max-w-2xl mx-auto px-4">
      {/* Messages */}
      {recentMessages.length > 0 && (
        <div className="mb-4 space-y-2 max-h-48 overflow-y-auto">
          {recentMessages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className="max-w-[80%] px-3 py-2 rounded-xl text-sm"
                style={{
                  background:
                    msg.role === "user"
                      ? "rgba(0, 212, 255, 0.1)"
                      : "var(--j-surface)",
                  border: `1px solid ${
                    msg.role === "user"
                      ? "rgba(0, 212, 255, 0.2)"
                      : "var(--j-border)"
                  }`,
                  color: "var(--j-text)",
                }}
              >
                {msg.text}
                {msg.source && msg.role === "assistant" && (
                  <span className="mono text-[9px] ml-2 opacity-40">
                    {msg.source}
                  </span>
                )}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      )}

      {/* Input bar */}
      <div
        className="glass flex items-center gap-2 px-3 py-2"
        style={{ borderRadius: "14px" }}
      >
        {/* Mic button */}
        <button
          onClick={toggleMic}
          className="w-9 h-9 rounded-xl flex items-center justify-center text-lg transition-all flex-shrink-0"
          style={{
            background: listening
              ? "rgba(255, 61, 87, 0.15)"
              : "rgba(0, 212, 255, 0.08)",
            color: listening ? "var(--j-red)" : "var(--j-cyan)",
            border: `1px solid ${
              listening
                ? "rgba(255, 61, 87, 0.2)"
                : "rgba(0, 212, 255, 0.15)"
            }`,
          }}
          title={listening ? "Stop listening" : "Start voice input"}
        >
          {listening ? "\u25FC" : "\uD83C\uDFA4"}
        </button>

        {/* Text input */}
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={listening ? "Listening..." : "Ask KALI anything..."}
          disabled={listening || isLoading}
          className="flex-1 bg-transparent outline-none text-sm placeholder-opacity-30"
          style={{
            color: "var(--j-text)",
            caretColor: "var(--j-cyan)",
          }}
        />

        {/* Send button */}
        <button
          onClick={() => send(text)}
          disabled={!text.trim() || isLoading}
          className="w-9 h-9 rounded-xl flex items-center justify-center transition-all flex-shrink-0"
          style={{
            background: text.trim()
              ? "rgba(0, 212, 255, 0.15)"
              : "transparent",
            color: text.trim() ? "var(--j-cyan)" : "var(--j-text-muted)",
            border: `1px solid ${
              text.trim() ? "rgba(0, 212, 255, 0.2)" : "transparent"
            }`,
          }}
        >
          {"\u2192"}
        </button>
      </div>

      {/* Loading indicator */}
      {isLoading && (
        <div
          className="text-center mt-2 mono text-[10px] tracking-[3px]"
          style={{ color: "var(--j-amber)" }}
        >
          PROCESSING
        </div>
      )}
    </div>
  );
}
