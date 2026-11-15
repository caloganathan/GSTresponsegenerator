/**
 * Dynamic clarifying questions step.
 *
 * Displays targeted Indian GST Act questions generated from the extracted
 * notice (e.g., OCR figure confirmation, ITC mismatch root cause, DRC-03
 * payments, s.74 intent, Personal Hearing u/s 75(4), and client context).
 */
export default function ClarifyingQuestions({
  questions = [],
  answers = {},
  onAnswer,
}) {
  if (!questions.length) {
    return (
      <div className="card card-pad">
        <p className="muted">
          All required notice details were extracted cleanly. You can proceed
          directly to generate the response.
        </p>
      </div>
    );
  }

  return (
    <div className="qa-list">
      {questions.map((q, index) => {
        const value = answers[q.id] ?? q.default_value ?? '';
        return (
          <div
            key={q.id}
            className={`qa-card ${q.priority === 'high' ? 'qa-card-high' : ''}`}
          >
            <div className="qa-card-head">
              <span className="qa-step-num">Q{index + 1}</span>
              <span className="qa-category">{q.category}</span>
              {q.priority === 'high' && (
                <span className="qa-priority">Important</span>
              )}
            </div>

            <div className="qa-question">{q.question}</div>

            {q.snippet && (
              <div className="qa-snippet">
                <span className="qa-snippet-label">Read from notice:</span>{' '}
                <code>{q.snippet}</code>
              </div>
            )}

            {(q.type === 'choice' || q.type === 'yes_no') && Array.isArray(q.options) ? (
              <div className="qa-options">
                {q.options.map((opt) => {
                  const selected = value === opt;
                  return (
                    <button
                      key={opt}
                      type="button"
                      className={`qa-option ${selected ? 'selected' : ''}`}
                      onClick={() => onAnswer(q, opt)}
                    >
                      <span className="qa-radio" aria-hidden="true">
                        {selected ? '●' : '○'}
                      </span>
                      <span>{opt}</span>
                    </button>
                  );
                })}
              </div>
            ) : q.id === 'additional_context' ? (
              <textarea
                className="input qa-textarea"
                rows={3}
                placeholder="Optional: e.g., supplier invoices and e-way bills are on file, or specific facts to highlight..."
                value={value}
                onChange={(e) => onAnswer(q, e.target.value)}
              />
            ) : (
              <input
                type="text"
                className="input"
                value={value}
                placeholder="Enter your answer…"
                onChange={(e) => onAnswer(q, e.target.value)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
