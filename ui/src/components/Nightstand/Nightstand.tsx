import { useState, useEffect } from "react";

export function Nightstand() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(interval);
  }, []);

  const hours = time.getHours().toString().padStart(2, "0");
  const minutes = time.getMinutes().toString().padStart(2, "0");
  const isNight = time.getHours() >= 22 || time.getHours() < 6;

  return (
    <div className="flex flex-col items-center justify-center h-full gap-6">
      <div className="text-8xl font-thin text-white tracking-wider">{hours}:{minutes}</div>
      <div className="text-xl text-gray-500">{time.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}</div>
      {isNight && <div className="text-sky-400/60 text-lg mt-8">Sleep well</div>}
    </div>
  );
}
