"use client";

import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api-client";
import { RefreshCw } from "lucide-react";

type TokenCheckButtonProps = {
  profileIds: string[];
  disabled: boolean;
};

export function TokenCheckButton({ profileIds, disabled }: TokenCheckButtonProps) {
  const [loading, setLoading] = useState(false);

  const handleCheck = useCallback(async () => {
    if (profileIds.length === 0) {
      toast.error("Vui lòng chọn ít nhất 1 profile.");
      return;
    }
    setLoading(true);
    try {
      await apiFetch<Record<string, { token_status: string }>>(
        "/api/profiles/check-tokens",
        {
          method: "POST",
          body: { uids: profileIds },
        }
      );
      // Wait a moment for SSE-driven updates, then show result toast
      toast.success("Đã gửi yêu cầu kiểm tra token.");
      setLoading(false);
    } catch (e) {
      if (e instanceof Error) toast.error(e.message);
      setLoading(false);
    }
  }, [profileIds]);

  return (
    <Button
      variant="outline"
      onClick={handleCheck}
      disabled={disabled || loading}
      className="h-8 px-3 text-[9pt] gap-1.5"
    >
      <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
      Kiểm tra token
    </Button>
  );
}
