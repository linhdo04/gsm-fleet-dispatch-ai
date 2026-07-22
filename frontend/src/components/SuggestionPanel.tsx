import type { RepositioningSuggestion } from "../types";

interface Props {
  suggestions: RepositioningSuggestion[];
}

export default function SuggestionPanel({ suggestions }: Props) {
  return (
    <div className="panel">
      <h2>Gợi ý điều xe</h2>
      <p className="panel-caveat">
        Tài xế, zone, khoảng cách và xác suất chấp nhận là số <strong>thật</strong> từ Acceptance Probability Model
        (Tuần 3) chạy trên Repositioning Suggester — chỉ câu văn giải thích còn là template, chưa gọi Claude/GPT API
        thật (chưa cấu hình API key).
      </p>
      {suggestions.length === 0 && <p className="muted">Không có zone thiếu xe đáng kể ở kịch bản này.</p>}
      <ul className="suggestion-list">
        {suggestions.map((s) => (
          <li key={s.suggestion_id} className="suggestion-item">
            <div className="suggestion-header">
              <strong>{s.driver_id}</strong>
              <span className="badge">{Math.round(s.acceptance_probability * 100)}% chấp nhận</span>
            </div>
            <p>{s.explanation}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
