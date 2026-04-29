interface Props {
  transcript: string;
}

export function LiveTranscript({ transcript }: Props) {
  if (!transcript) return null;
  return (
    <div
      className="live-transcript"
      style={{
        textAlign: "center",
        color: "var(--j-text-dim)",
        fontStyle: "italic",
        maxWidth: 480,
        margin: "12px auto",
      }}
    >
      «{transcript}»
    </div>
  );
}
