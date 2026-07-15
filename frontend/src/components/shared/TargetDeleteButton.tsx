"use client";

import { useState, type MouseEvent } from "react";
import { LoaderCircle, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { apiDelete } from "@/lib/api-client";

type DeleteTarget = {
  id: string;
  name: string;
  type: "personal" | "page" | "group" | "external_page";
};

export function TargetDeleteButton({ target, disabled, onDeleted }: {
  target: DeleteTarget;
  disabled?: boolean;
  onDeleted: () => void | Promise<void>;
}) {
  const [deleting, setDeleting] = useState(false);

  async function handleDelete(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    const warning = target.type === "personal"
      ? `Xóa tài khoản “${target.name}”? Các Fanpage, Group và dữ liệu liên kết của tài khoản này cũng sẽ bị xóa.`
      : `Xóa mục tiêu “${target.name}”?`;
    if (!window.confirm(warning)) return;

    setDeleting(true);
    try {
      const [targetType, targetId] = target.id.split(":", 2);
      if (!targetType || !targetId) throw new Error("Mã mục tiêu không hợp lệ.");
      await apiDelete(`/api/post-targets/${encodeURIComponent(targetType)}/${encodeURIComponent(targetId)}`);
      toast.success(`Đã xóa ${target.name}`);
      await onDeleted();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Không xóa được mục tiêu.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      className="shrink-0 text-slate-400 hover:bg-red-50 hover:text-red-600"
      onClick={handleDelete}
      disabled={disabled || deleting}
      title={`Xóa ${target.name}`}
      aria-label={`Xóa ${target.name}`}
    >
      {deleting ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
    </Button>
  );
}
