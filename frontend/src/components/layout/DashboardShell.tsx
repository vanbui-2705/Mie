import { SideNav } from "./SideNav";
import { TopBar } from "./TopBar";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen w-full flex-col md:h-screen md:flex-row md:overflow-hidden">
      <SideNav />
      <div className="flex min-h-0 flex-1 flex-col md:overflow-hidden">
        <TopBar />
        <main className="min-h-0 flex-1 p-3 scroll-smooth sm:p-4 md:overflow-auto md:p-5">
          {children}
        </main>
      </div>
    </div>
  );
}
