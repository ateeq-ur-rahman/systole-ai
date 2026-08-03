import { useState } from "react";
import { Sparkles } from "lucide-react";
import { api } from "../api/client";

const SUGGESTIONS = [
  "Why is my storage full?",
  "Where is my storage being used?",
  "Which files are duplicates?",
  "How much storage can I recover?",
  "Explain today's storage changes.",
];

export function AskPanel() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function ask(q: string) {
    if (!q.trim()) return;
    setLoading(true);
    setQuestion(q);
    try {
      const result = await api.ask(q);
      setAnswer(result.answer);
    } catch {
      setAnswer("Couldn't reach Systole AI — make sure the background service is running.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="ask-panel">
      <div className="ask-input-row">
        <input
          placeholder="Ask Systole AI about your storage…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(question)}
        />
        <button className="btn btn-primary" onClick={() => ask(question)} disabled={loading}>
          <Sparkles size={14} strokeWidth={2} />
          {loading ? "Thinking…" : "Ask"}
        </button>
      </div>
      <div className="ask-suggestions">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="ask-suggestion" onClick={() => ask(s)}>
            {s}
          </button>
        ))}
      </div>
      {answer && <div className="ask-answer fade-in">{answer}</div>}
    </div>
  );
}
