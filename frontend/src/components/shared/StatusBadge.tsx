import { statusToVariant } from "@/types";

type BadgeVariant = ReturnType<typeof statusToVariant>;

const variantClass: Record<string, string> = {
  success: "status-badge--success",
  warning: "status-badge--warning",
  danger: "status-badge--danger",
  info: "status-badge--info",
  default: "status-badge--default",
};

type StatusBadgeProps = {
  status: string;
  className?: string;
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const variant = statusToVariant(status) as string;
  return (
    <span className={"status-badge " + (variantClass[variant] ?? variantClass.default) + " " + (className || "")}>
      {status}
    </span>
  );
}
