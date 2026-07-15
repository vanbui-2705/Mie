"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { KeyRound, RefreshCw, Save, Trash2, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiDelete, apiFetch, apiPatch, apiPost, setAuthSession, getAuthToken, type AuthUser } from "@/lib/api-client";

type ManagedUser = AuthUser & {
  created_at?: string;
  has_password?: boolean;
};
type RoleOption = { id: string; name: string; display_name: string; is_system: boolean };

type UserDraft = {
  role: string;
  status: string;
  password: string;
};

function formatDate(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("vi-VN");
}

export default function UsersPage() {
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [rows, setRows] = useState<ManagedUser[]>([]);
  const [drafts, setDrafts] = useState<Record<string, UserDraft>>({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState("");
  const [deletingId, setDeletingId] = useState("");
  const [creating, setCreating] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("user");
  const [authChecked, setAuthChecked] = useState(false);
  const [roleOptions, setRoleOptions] = useState<RoleOption[]>([]);

  const isAdmin = Boolean(currentUser?.permissions?.includes("user:read"));

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<ManagedUser[]>("/api/auth/users");
      setRows(data ?? []);
      const nextDrafts: Record<string, UserDraft> = {};
      for (const row of data ?? []) {
        nextDrafts[row.id] = {
          role: row.role || "user",
          status: row.status || "active",
          password: "",
        };
      }
      setDrafts(nextDrafts);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Không tải được danh sách người dùng");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    apiFetch<AuthUser>("/api/auth/me")
      .then((me) => {
        setCurrentUser(me);
        const token = getAuthToken();
        if (token) setAuthSession(token, me);
        if (me.permissions?.includes("user:read")) {
          void loadUsers();
        }
        if (me.permissions?.includes("role:read")) {
          void apiFetch<RoleOption[]>("/api/roles").then(setRoleOptions).catch(() => setRoleOptions([]));
        }
      })
      .catch(() => {})
      .finally(() => setAuthChecked(true));
  }, [loadUsers]);

  const stats = useMemo(() => {
    const active = rows.filter((row) => row.status === "active").length;
    const admins = rows.filter((row) => row.role === "admin" || row.role === "super_admin").length;
    return { total: rows.length, active, admins };
  }, [rows]);

  function updateDraft(id: string, patch: Partial<UserDraft>) {
    setDrafts((current) => ({
      ...current,
      [id]: {
        ...(current[id] ?? { role: "user", status: "active", password: "" }),
        ...patch,
      },
    }));
  }

  async function submitCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    try {
      await apiPost<ManagedUser>("/api/auth/users", {
        username: newUsername,
        password: newPassword,
        role: newRole,
      });
      setNewUsername("");
      setNewPassword("");
      setNewRole("user");
      toast.success("Đã tạo người dùng mới");
      await loadUsers();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Tạo người dùng thất bại");
    } finally {
      setCreating(false);
    }
  }

  async function submitUpdate(row: ManagedUser) {
    const draft = drafts[row.id];
    if (!draft) return;
    setSavingId(row.id);
    try {
      const body: Record<string, string> = {
        status: draft.status,
      };
      if (draft.password.trim()) body.password = draft.password.trim();
      await apiPatch<ManagedUser>(`/api/auth/users/${row.id}`, body);
      if (draft.role !== row.role && currentUser?.permissions?.includes("permission:assign")) {
        await apiFetch(`/api/users/${row.id}/roles`, { method: "PUT", body: { roles: [draft.role] } });
      }
      toast.success(`Đã cập nhật ${row.username}`);
      await loadUsers();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Cập nhật người dùng thất bại");
    } finally {
      setSavingId("");
    }
  }

  async function submitDelete(row: ManagedUser) {
    if (currentUser?.id === row.id) {
      toast.error("Không thể xóa người dùng đang đăng nhập");
      return;
    }
    if (!window.confirm(`Xóa người dùng ${row.username}? Dữ liệu của người dùng này cũng sẽ bị xóa.`)) {
      return;
    }
    setDeletingId(row.id);
    try {
      await apiDelete<{ deleted: boolean }>(`/api/auth/users/${row.id}`);
      toast.success(`Đã xóa ${row.username}`);
      await loadUsers();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Xóa người dùng thất bại");
    } finally {
      setDeletingId("");
    }
  }

  if (!authChecked) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="rounded-lg border bg-white px-4 py-3 text-sm shadow-sm" style={{ borderColor: "var(--border)", color: "var(--text-sub)" }}>
          Đang kiểm tra quyền truy cập...
        </div>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md rounded-lg border bg-white p-6 text-center shadow-sm" style={{ borderColor: "var(--border)" }}>
          <h1 className="text-lg font-semibold" style={{ color: "var(--text-main)" }}>
            Không có quyền truy cập
          </h1>
          <p className="mt-2 text-sm" style={{ color: "var(--text-sub)" }}>
            Tài khoản hiện tại không có quyền xem danh sách người dùng.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-xl font-semibold" style={{ color: "var(--text-main)" }}>
            Quản lý người dùng
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--text-sub)" }}>
            Tạo người dùng riêng để tách biệt tài khoản Facebook, trang, tác vụ, nhật ký và phiên trình duyệt.
          </p>
        </div>
        <Button type="button" variant="outline" onClick={loadUsers} disabled={loading}>
          <RefreshCw className="h-4 w-4" />
          Tải lại
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border bg-white p-4" style={{ borderColor: "var(--border)" }}>
          <div className="text-xs" style={{ color: "var(--text-sub)" }}>Tổng người dùng</div>
          <div className="mt-1 text-2xl font-semibold" style={{ color: "var(--text-main)" }}>{stats.total}</div>
        </div>
        <div className="rounded-lg border bg-white p-4" style={{ borderColor: "var(--border)" }}>
          <div className="text-xs" style={{ color: "var(--text-sub)" }}>Đang hoạt động</div>
          <div className="mt-1 text-2xl font-semibold" style={{ color: "var(--success)" }}>{stats.active}</div>
        </div>
        <div className="rounded-lg border bg-white p-4" style={{ borderColor: "var(--border)" }}>
          <div className="text-xs" style={{ color: "var(--text-sub)" }}>Admin</div>
          <div className="mt-1 text-2xl font-semibold" style={{ color: "var(--accent)" }}>{stats.admins}</div>
        </div>
      </div>

      <section className="rounded-lg border bg-white p-4" style={{ borderColor: "var(--border)" }}>
        <SectionEyebrow label="Tạo người dùng mới" />
        <form className="mt-4 grid gap-3 lg:grid-cols-[1fr_1fr_160px_auto]" onSubmit={submitCreate}>
          <div className="grid gap-1.5">
            <Label htmlFor="new-username">Username</Label>
            <Input id="new-username" value={newUsername} onChange={(event) => setNewUsername(event.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="new-password">Mật khẩu</Label>
            <Input id="new-password" type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="new-role">Role</Label>
            <select
              id="new-role"
              className="h-8 rounded-lg border bg-transparent px-2 text-sm"
              style={{ borderColor: "var(--border)" }}
              value={newRole}
              onChange={(event) => setNewRole(event.target.value)}
            >
              {(roleOptions.length ? roleOptions : [{ id: "user", name: "user", display_name: "User", is_system: true }]).filter((role) => role.name !== "super_admin" || currentUser?.permissions?.includes("tenant:manage:any")).map((role) => <option key={role.id} value={role.name}>{role.name}</option>)}
            </select>
          </div>
          <div className="flex items-end">
            <Button type="submit" disabled={creating || !newUsername.trim() || newPassword.length < 6}>
              <UserPlus className="h-4 w-4" />
              Tạo người dùng
            </Button>
          </div>
        </form>
      </section>

      <section className="rounded-lg border bg-white p-4" style={{ borderColor: "var(--border)" }}>
        <SectionEyebrow label="Danh sách người dùng" />
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-[900px] w-full border-separate border-spacing-y-2 text-sm">
            <thead>
              <tr style={{ color: "var(--text-sub)" }}>
                <th className="px-2 text-left font-medium">Username</th>
                <th className="px-2 text-left font-medium">Role</th>
                <th className="px-2 text-left font-medium">Status</th>
                <th className="px-2 text-left font-medium">Mật khẩu mới</th>
                <th className="px-2 text-left font-medium">Tạo lúc</th>
                <th className="px-2 text-left font-medium">Trạng thái</th>
                <th className="px-2 text-right font-medium">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={7} className="px-2 py-8 text-center" style={{ color: "var(--text-sub)" }}>
                    Đang tải người dùng...
                  </td>
                </tr>
              )}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-2 py-8 text-center" style={{ color: "var(--text-sub)" }}>
                    Chưa có người dùng nào.
                  </td>
                </tr>
              )}
              {!loading &&
                rows.map((row) => {
                  const draft = drafts[row.id] ?? { role: row.role, status: row.status || "active", password: "" };
                  const isSelf = currentUser?.id === row.id;
                  return (
                    <tr key={row.id} className="rounded-md bg-slate-50">
                      <td className="rounded-l-md px-2 py-2">
                        <div className="font-medium" style={{ color: "var(--text-main)" }}>{row.username}</div>
                        <div className="text-[11px]" style={{ color: "var(--text-sub)" }}>{row.id}</div>
                      </td>
                      <td className="px-2 py-2">
                        <select
                          className="h-8 w-full rounded-lg border bg-white px-2 text-sm"
                          style={{ borderColor: "var(--border)" }}
                          value={draft.role}
                          onChange={(event) => updateDraft(row.id, { role: event.target.value })}
                        >
                          {(roleOptions.length ? roleOptions : [{ id: "user", name: "user", display_name: "User", is_system: true }]).filter((role) => role.name !== "super_admin" || currentUser?.permissions?.includes("tenant:manage:any")).map((role) => <option key={role.id} value={role.name}>{role.name}</option>)}
                        </select>
                      </td>
                      <td className="px-2 py-2">
                        <select
                          className="h-8 w-full rounded-lg border bg-white px-2 text-sm"
                          style={{ borderColor: "var(--border)" }}
                          value={draft.status}
                          onChange={(event) => updateDraft(row.id, { status: event.target.value })}
                          disabled={isSelf}
                        >
                          <option value="active">active</option>
                          <option value="disabled">disabled</option>
                        </select>
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex items-center gap-2">
                          <KeyRound className="h-4 w-4" style={{ color: "var(--text-sub)" }} />
                          <Input
                            type="password"
                            placeholder="Để trống nếu không đổi"
                            value={draft.password}
                            onChange={(event) => updateDraft(row.id, { password: event.target.value })}
                          />
                        </div>
                      </td>
                      <td className="px-2 py-2" style={{ color: "var(--text-sub)" }}>{formatDate(row.created_at)}</td>
                      <td className="px-2 py-2">
                        <StatusBadge status={row.status || "active"} />
                      </td>
                      <td className="rounded-r-md px-2 py-2">
                        <div className="flex justify-end gap-2">
                          <Button type="button" size="sm" onClick={() => submitUpdate(row)} disabled={savingId === row.id}>
                            <Save className="h-3.5 w-3.5" />
                            Lưu
                          </Button>
                          <Button
                            type="button"
                            size="icon-sm"
                            variant="destructive"
                            onClick={() => submitDelete(row)}
                            disabled={isSelf || deletingId === row.id}
                            title={isSelf ? "Không thể xóa người dùng hiện tại" : "Xóa người dùng"}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
