"use client";

import { useMemo, useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

export type BulkImportDialogProps = {
  open: boolean;
  onClose: () => void;
  onImport: (text: string) => Promise<void>;
};

export function BulkImportDialog({ open, onClose, onImport }: BulkImportDialogProps) {
  const [text, setText] = useState("");
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");

  const lines = useMemo(
    () => text.replace(/\r\n/g, "\n").split("\n").filter((line) => line.trim()),
    [text],
  );
  const validLines = useMemo(
    () => lines.filter((line) => {
      const [uid, token] = line.split("|", 2);
      return Boolean(uid?.trim() && token?.trim());
    }),
    [lines],
  );

  if (!open) return null;

  const handleClose = () => {
    if (!importing) onClose();
  };

  const handleImport = async () => {
    if (!text.trim() || validLines.length === 0) return;
    setImporting(true);
    setError("");
    try {
      await onImport(text.trim());
      setText("");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không nhập được danh sách UID|TOKEN");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-2 sm:p-4"
      onClick={handleClose}
    >
      <div
        className="flex max-h-[calc(100dvh-1rem)] w-full max-w-2xl flex-col overflow-hidden rounded-md bg-white shadow-xl sm:max-h-[calc(100vh-2rem)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="shrink-0 border-b p-4 sm:p-5" style={{ borderColor: "var(--border)" }}>
          <h2 className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
            Nhập Facebook Account
          </h2>
          <p className="mt-1 text-[9pt]" style={{ color: "var(--muted-foreground)" }}>
            Dán danh sách UID|TOKEN, mỗi dòng một tài khoản. Hệ thống sẽ tự lấy tên từ Facebook; có thể nhập thêm UID|TOKEN|TÊN để đặt tên thủ công.
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-4 sm:p-5">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[9pt]" style={{ color: "var(--muted-foreground)" }}>
            <span>{lines.length} dòng, {validLines.length} dòng đúng định dạng</span>
            <span>Định dạng: UID|TOKEN hoặc UID|TOKEN|TÊN</span>
          </div>
          <Textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={"1000123456|EAAG...\n1000654321|EAAG...|Tài khoản bán hàng\n1000765432|EAAG..."}
            className="h-[42dvh] min-h-[180px] max-h-[42dvh] resize-none overflow-y-auto overflow-x-auto text-[9pt] [field-sizing:fixed] sm:min-h-[220px]"
            disabled={importing}
            wrap="off"
            style={{ fontFamily: "var(--font-mono)", fontSize: "9.5pt" }}
          />
          {error && (
            <div
              className="mt-3 rounded border px-3 py-2 text-[9pt]"
              style={{
                borderColor: "var(--danger)",
                color: "var(--danger)",
                backgroundColor: "var(--danger-soft)",
              }}
            >
              {error}
            </div>
          )}
        </div>

        <div className="shrink-0 border-t bg-white p-3 sm:p-4" style={{ borderColor: "var(--border)" }}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-[9pt]" style={{ color: "var(--muted-foreground)" }}>
              Sẽ gửi {validLines.length} account hợp lệ lên backend.
            </div>
            <div className="flex w-full justify-end gap-2 sm:w-auto">
              <Button variant="outline" onClick={handleClose} disabled={importing} className="h-8 flex-1 px-4 text-[9pt] sm:flex-none">
                Hủy
              </Button>
              <Button
                onClick={handleImport}
                disabled={!text.trim() || validLines.length === 0 || importing}
                className="h-8 flex-1 px-4 text-[9pt] text-white sm:flex-none"
                style={{ backgroundColor: "var(--accent)" }}
              >
                {importing ? "Đang nhập..." : "Xác nhận nhập"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
