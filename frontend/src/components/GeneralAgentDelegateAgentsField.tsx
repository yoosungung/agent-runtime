import type { AccessResource } from "../hooks/useMyUserMeta";

interface GeneralAgentDelegateAgentsFieldProps {
  agents: AccessResource[];
  selected: string[];
  onChange: (names: string[]) => void;
  loading?: boolean;
}

export function GeneralAgentDelegateAgentsField({
  agents,
  selected,
  onChange,
  loading = false,
}: GeneralAgentDelegateAgentsFieldProps) {
  function toggle(name: string) {
    onChange(
      selected.includes(name)
        ? selected.filter((n) => n !== name)
        : [...selected, name],
    );
  }

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        Delegate agents (optional)
      </label>
      {loading ? (
        <p className="text-sm text-gray-500">Loading agents…</p>
      ) : agents.length === 0 ? (
        <p className="text-sm text-gray-500">
          위임할 agent가 없습니다. ACL이 있는 agent만 선택할 수 있습니다.
        </p>
      ) : (
        <ul className="space-y-2 border rounded-md p-3 max-h-48 overflow-y-auto">
          {agents.map((agent) => (
            <li key={agent.name}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.includes(agent.name)}
                  onChange={() => toggle(agent.name)}
                />
                <span className="font-mono">{agent.name}</span>
                <span className="text-gray-500 text-xs">({agent.version})</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-gray-500 mt-1">
        선택한 agent는 invoke-internal로 위임 tool이 노출됩니다.
      </p>
    </div>
  );
}
