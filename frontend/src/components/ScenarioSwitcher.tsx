import type { ScenarioKey } from "../types";
import { SCENARIOS } from "../mock/scenario";

interface Props {
  active: ScenarioKey;
  onChange: (scenario: ScenarioKey) => void;
}

export default function ScenarioSwitcher({ active, onChange }: Props) {
  return (
    <div className="scenario-switcher" role="group" aria-label="Chọn kịch bản">
      {SCENARIOS.map((s) => (
        <button
          key={s.key}
          className={`scenario-btn${s.key === active ? " active" : ""}`}
          onClick={() => onChange(s.key)}
          type="button"
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
