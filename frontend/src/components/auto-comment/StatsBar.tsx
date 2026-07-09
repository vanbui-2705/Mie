import type { TaskStats } from "@/types";

type StatsBarProps = {
  stats: TaskStats | null;
};

export function StatsBar({ stats }: StatsBarProps) {
  if (!stats) return null;

  return (
    <div
      className="stats-bar-dark flex flex-wrap items-center gap-x-5 gap-y-2 text-[9pt]"
      style={{ borderRadius: 4 }}
    >
      <span>
        Tổng: <strong style={{ color: "var(--accent)" }}>{stats.total}</strong>
      </span>
      <span>
        Đã chạy: <strong style={{ color: "var(--surface-dark-fg)" }}>{stats.processed}</strong>
      </span>
      <span>
        Thành công: <strong style={{ color: "var(--success)" }}>{stats.success}</strong>
      </span>
      <span>
        Thất bại: <strong style={{ color: "var(--danger)" }}>{stats.failed}</strong>
      </span>
      <span>
        Đang chờ proxy: <strong style={{ color: "var(--warning)" }}>{stats.waitingProxy}</strong>
      </span>
    </div>
  );
}
